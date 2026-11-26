"""Streamlit Community Cloud 앱이 잠들지 않도록 헤드리스 브라우저로 접속한다.

잠든 상태면 'Yes, get this app back up!' 버튼을 눌러 깨운다.
GitHub Actions(.github/workflows/keep-awake.yml)에서 실행된다.
"""
import os
import sys

from playwright.sync_api import sync_playwright

APP_URL = os.environ.get("APP_URL", "https://parkdaehee.streamlit.app/")
WAKE_TEXT = "get this app back up"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(10_000)

        button = page.get_by_role("button", name=WAKE_TEXT, exact=False)
        if button.count() > 0:
            print("앱이 잠들어 있어 깨우기 버튼을 누릅니다.")
            button.first.click()
            page.wait_for_timeout(60_000)
        else:
            print("앱이 깨어 있습니다.")

        # 잠들기 화면이 여전히 남아 있으면 실패로 표시
        if page.get_by_role("button", name=WAKE_TEXT, exact=False).count() > 0:
            print("오류: 깨우기 버튼을 눌렀지만 앱이 아직 깨어나지 않았습니다.")
            browser.close()
            return 1

        # 앱 본체(iframe 안)가 뜨는지 확인 (확인 못해도 접속 자체는 기록되므로 실패 처리하지 않음)
        try:
            page.frame_locator("iframe[title='streamlitApp']").locator(
                "[data-testid='stApp']"
            ).wait_for(timeout=90_000)
            print("앱 화면 로드 확인:", APP_URL)
        except Exception:
            print("참고: 앱 화면 요소를 확인하지 못했습니다. 페이지 제목:", page.title())
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
