import os
import shutil
import time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

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


def ask_chatgpt(prompt_text: str) -> str:

    clone_profile_if_needed()

    with sync_playwright() as p:

        context = p.chromium.launch_persistent_context(
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

        try:

            page = context.new_page()

            page.goto(
                "https://chatgpt.com/",
                wait_until="networkidle",
            )

            page.wait_for_selector(
                "#prompt-textarea",
                timeout=30000,
            )

            textarea = page.locator("#prompt-textarea")
            textarea.click()
            page.keyboard.insert_text(prompt_text)

            send_button = page.locator(
                "button#composer-submit-button"
            )

            send_button.wait_for(
                state="visible",
                timeout=10000,
            )

            send_button.click()

            try:
                page.wait_for_selector(
                    '[data-testid="stop-button"]',
                    state="attached",
                    timeout=5000,
                )
            except Exception:
                pass

            page.wait_for_selector(
                '[data-testid="stop-button"]',
                state="detached",
                timeout=90000,
            )

            time.sleep(2)

            assistant_messages = page.locator(
                '[data-message-author-role="assistant"]'
            )

            if assistant_messages.count() == 0:
                raise RuntimeError(
                    "No assistant response found on the page"
                )

            answer = assistant_messages.last.inner_text()

            return answer

        finally:
            context.close()