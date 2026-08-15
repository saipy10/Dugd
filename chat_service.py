import os
import shutil
import time
import queue
import threading
import traceback
from typing import Generator
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Playwright, BrowserContext, Page

from logger import logger

load_dotenv()

USERNAME = os.getenv("WINDOWS_USERNAME")
PROFILE_NAME = os.getenv("PROFILE_NAME", "Default")

if not USERNAME:
    raise ValueError("WINDOWS_USERNAME is missing in .env")

SOURCE_PROFILE_DIR = (
    f"C:/Users/{USERNAME}/AppData/Local/Google/Chrome/User Data"
)

CLONE_PROFILE_DIR = (
    f"C:/Users/{USERNAME}/playwright_chrome_profile"
)


def clone_profile_if_needed(force_refresh: bool = False):
    dest_profile_path = os.path.join(CLONE_PROFILE_DIR, PROFILE_NAME)

    if os.path.exists(dest_profile_path) and not force_refresh:
        return

    src_profile_path = os.path.join(SOURCE_PROFILE_DIR, PROFILE_NAME)

    if not os.path.exists(src_profile_path):
        raise FileNotFoundError(
            f"Chrome profile not found: {src_profile_path}"
        )

    os.makedirs(CLONE_PROFILE_DIR, exist_ok=True)

    shutil.copytree(
        src_profile_path,
        dest_profile_path,
        dirs_exist_ok=True,
    )

    local_state_src = os.path.join(
        SOURCE_PROFILE_DIR,
        "Local State",
    )

    local_state_dst = os.path.join(
        CLONE_PROFILE_DIR,
        "Local State",
    )

    if os.path.exists(local_state_src):
        shutil.copy2(local_state_src, local_state_dst)


class ChatGPTBrowserSession:
    def __init__(self):
        self.playwright: Playwright = None
        self.context: BrowserContext = None
        self.page: Page = None

    def start(self):
        if self.page:
            try:
                # Check if the page/browser is still alive by accessing a property
                self.page.url
                return
            except Exception:
                # Page or browser is dead, clean up and restart
                logger.warning("Existing browser session is dead, cleaning up and restarting.")
                self.close()

        logger.debug("Cloning profile if needed.")
        clone_profile_if_needed()
        logger.debug("Starting Playwright.")
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(
            CLONE_PROFILE_DIR,
            channel="chrome",
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-size=1440,900",
            ],
            viewport={
                "width": 1440,
                "height": 900,
            },
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        logger.debug("Navigating to https://chatgpt.com/ (wait_until=networkidle).")
        self.page.goto("https://chatgpt.com/", wait_until="networkidle")

    def close(self):
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
            self.context = None
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
        self.page = None


def clean_extracted_text(text: str) -> str:
    cleaned = text.strip()
    # Find "Edit" within the first 10 characters to bypass any invisible/control characters
    idx = cleaned.find("Edit")
    if 0 <= idx < 10:
        return cleaned[idx + 4:].strip()
    return cleaned


session = ChatGPTBrowserSession()


def ask_chatgpt_internal(prompt_text: str) -> Generator[str, None, None]:
    try:
        logger.debug("Preparing browser session for new prompt.")
        yield "_⚙️ Preparing browser..._\n\n"
        session.start()
        page = session.page
        
        logger.debug("Navigating to chat UI.")
        yield "_⚙️ Navigating to chat..._\n\n"

        # Avoid full page reloads by checking current URL and using client-side navigation
        current_url = page.url
        # Check if there are already message elements on the page (indicating an active thread)
        has_messages = page.locator('[data-message-author-role]').count() > 0
        
        # If we are in a thread (/c/...) or have active messages on the page, or prompt is not visible,
        # trigger a client-side navigation to a clean new chat.
        if "chatgpt.com/c/" in current_url or has_messages or not page.locator("#prompt-textarea").is_visible():
            try:
                navigated = page.evaluate(
                    """
                    () => {
                        const selectors = [
                            'a[href="/"]',
                            'button[data-testid="new-chat-button"]',
                            '[aria-label="New chat"]'
                        ];
                        for (const selector of selectors) {
                            const elem = document.querySelector(selector);
                            if (elem) {
                                elem.click();
                                return true;
                            }
                        }
                        return false;
                    }
                    """
                )
                if navigated:
                    # Wait for old messages to detach from the DOM so we count from a clean slate
                    try:
                        page.locator('[data-message-author-role]').wait_for(state="detached", timeout=3000)
                    except Exception:
                        pass
                    # Sleep briefly to let the Next.js page transition and DOM layout settle completely
                    time.sleep(0.5)
                    if "chatgpt.com/c/" in current_url:
                        page.wait_for_url(lambda url: "chatgpt.com/c/" not in url, timeout=3000)
                else:
                    raise RuntimeError("No client-side navigation element found")
            except Exception as e:
                logger.warning(f"Client-side navigation failed: {e}. Falling back to page reload.")
                page.goto("https://chatgpt.com/", wait_until="domcontentloaded")

        page.wait_for_selector(
            "#prompt-textarea",
            timeout=30000,
        )

        # Dismiss guest signup modal if it is overlaying the page
        auth_modal = page.locator('[data-testid="modal-no-auth-new-chat"]')
        if auth_modal.is_visible():
            page.keyboard.press("Escape")
            try:
                auth_modal.wait_for(state="hidden", timeout=2000)
            except Exception:
                logger.debug("No auth modal to wait for, or wait timed out.")
                pass

        logger.debug("Typing the prompt into the textarea.")
        yield "_⚙️ Typing prompt..._\n\n"
        textarea = page.locator("#prompt-textarea")
        textarea.click()
        time.sleep(0.3)
        page.keyboard.press("Control+a")
        page.keyboard.insert_text(prompt_text)

        send_button = page.locator(
            "button#composer-submit-button"
        )

        send_button.wait_for(
            state="visible",
            timeout=10000,
        )

        # Count current assistant messages before clicking send
        assistant_locator = page.locator(
            '[data-message-author-role="assistant"]'
        )
        initial_count = assistant_locator.count()

        logger.debug(f"Current assistant messages count: {initial_count}. Waiting for response to start.")
        yield "_⚙️ Waiting for ChatGPT to respond..._\n\n---\n\n"
        send_button.click()

        # Wait for the new message container to appear using native Playwright waiting (MutationObserver)
        new_message_locator = assistant_locator.nth(initial_count)
        try:
            new_message_locator.wait_for(state="attached", timeout=15000)
        except Exception:
            logger.error("Timeout waiting for assistant response to start (attached state).")
            raise RuntimeError("Timeout waiting for assistant response to start")

        # Poll text periodically and yield differences
        yielded_text = ""
        last_change_time = time.time()
        start_poll_time = time.time()
        has_started = False

        while True:
            # Consolidate DOM queries into a single JS evaluation to minimize CDP roundtrips.
            # Query the element by index dynamically to avoid stale handle errors if React unmounts it.
            state = page.evaluate(
                """
                ([selector, index]) => {
                    const elems = document.querySelectorAll(selector);
                    const elem = elems[index];
                    if (!elem) return null;
                    const markdown = elem.querySelector('.markdown');
                    const stopBtn = document.querySelector('[data-testid="stop-button"]');
                    return {
                        hasMarkdown: !!markdown,
                        text: markdown ? markdown.innerText : '',
                        rawText: elem.innerText,
                        isGenerating: !!stopBtn
                    };
                }
                """,
                ['[data-message-author-role="assistant"]', initial_count]
            )

            if not state:
                break

            if state["hasMarkdown"]:
                current_text = state["text"]
            else:
                current_text = state["rawText"]

            current_text = clean_extracted_text(current_text)

            is_generating = state["isGenerating"]
            if not has_started and (len(current_text) > 0 or is_generating):
                has_started = True
                last_change_time = time.time()

            if len(current_text) > len(yielded_text):
                delta = current_text[len(yielded_text):]
                yield delta
                yielded_text = current_text
                last_change_time = time.time()

            if has_started:
                # Stop polling when not generating and no new text has been typed for 1.5s
                if not is_generating and (time.time() - last_change_time > 1.5):
                    break
            else:
                # If not started yet, timeout after 15 seconds
                if time.time() - start_poll_time > 15:
                    logger.error("Timeout waiting for response text to start generating.")
                    raise RuntimeError("Timeout waiting for response to start")

            # Safety timeout (2 minutes)
            if time.time() - start_poll_time > 120:
                break

            time.sleep(0.1)

        # Final check to yield any remaining text
        state = page.evaluate(
            """
            ([selector, index]) => {
                const elems = document.querySelectorAll(selector);
                const elem = elems[index];
                if (!elem) return null;
                const markdown = elem.querySelector('.markdown');
                return {
                    hasMarkdown: !!markdown,
                    text: markdown ? markdown.innerText : '',
                    rawText: elem.innerText
                };
            }
            """,
            ['[data-message-author-role="assistant"]', initial_count]
        )

        if state:
            if state["hasMarkdown"]:
                final_text = state["text"]
            else:
                final_text = state["rawText"]
            final_text = clean_extracted_text(final_text)
            if len(final_text) > len(yielded_text):
                yield final_text[len(yielded_text):]

    except Exception as e:
        logger.exception("An error occurred during ask_chatgpt_internal execution")
        session.close()
        raise e


class PlaywrightWorker(threading.Thread):
    def __init__(self):
        super().__init__(name="PlaywrightWorker", daemon=True)
        self.task_queue = queue.Queue()

    def run(self):
        logger.info("Playwright worker thread ready (browser starts on first request).")

        while True:
            task = self.task_queue.get()
            if task == (None, None):
                logger.info("Shutting down browser session on worker thread...")
                try:
                    session.close()
                except Exception:
                    pass
                self.task_queue.task_done()
                break

            prompt_text, chunk_queue = task
            try:
                for chunk in ask_chatgpt_internal(prompt_text):
                    chunk_queue.put(chunk)
                chunk_queue.put(None)  # Success sentinel
            except Exception as e:
                chunk_queue.put(e)
            finally:
                self.task_queue.task_done()


# Start the background worker thread
worker = PlaywrightWorker()
worker.start()


def ask_chatgpt(prompt_text: str) -> Generator[str, None, None]:
    chunk_queue = queue.Queue()
    worker.task_queue.put((prompt_text, chunk_queue))

    while True:
        chunk = chunk_queue.get()
        if chunk is None:
            break
        if isinstance(chunk, Exception):
            raise chunk
        yield chunk