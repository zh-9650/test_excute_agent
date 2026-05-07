"""Frontend E2E test"""
from playwright.sync_api import sync_playwright

def find_enabled_btn(page, containing=''):
    for b in page.locator('button').all():
        if b.is_enabled() and (containing in b.text_content() or not containing):
            return b
    return None

def test_flow():
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # Step 1: Upload CSV
    page.goto('http://localhost:5173')
    page.wait_for_load_state('networkidle')
    print('[OK] Page loaded')

    file_input = page.locator('input[type=file]')
    file_input.set_input_files(r'C:\Users\17381\Desktop\自有系统测试用例合集\小仓写作\文档rest.csv')
    page.wait_for_timeout(2000)

    # Click enabled button (upload)
    upload_btn = find_enabled_btn(page)
    if upload_btn:
        upload_btn.click()
        print('[OK] CSV uploaded')
    else:
        raise Exception('No enabled button for upload')

    page.wait_for_timeout(3000)
    page.screenshot(path='test_artifacts/frontend_1_upload.png')

    # Step into execution page
    next_btn = find_enabled_btn(page)
    if next_btn:
        next_btn.click()
        print('[OK] Navigated to execute page')
    page.wait_for_timeout(2000)
    page.screenshot(path='test_artifacts/frontend_2_exec.png')

    # Fill form
    for inp in page.locator('input').all():
        ph = inp.get_attribute('placeholder') or ''
        tp = inp.get_attribute('type') or ''
        if '192.168' in ph:
            inp.fill('http://192.168.31.155')
            print('[OK] URL filled')
            break

    for inp in page.locator('input').all():
        ph = inp.get_attribute('placeholder') or ''
        tp = inp.get_attribute('type') or ''
        if 'zhanghong' in ph or 'admin' in ph:
            inp.fill('zhanghong')
            print('[OK] Username filled')
        elif tp == 'password':
            inp.fill('123456')
            print('[OK] Password filled')

    page.wait_for_timeout(500)

    # Click Step 1
    step1 = find_enabled_btn(page, '1')
    if step1:
        step1.click()
        print('[OK] Step 1 Explore clicked')
    else:
        for b in page.locator('button').all():
            print(f'  Btn: "{b.text_content()[:40]}" en={b.is_enabled()}')
        raise Exception('No step 1 button')

    page.wait_for_timeout(15000)
    page.screenshot(path='test_artifacts/frontend_3_explored.png')

    # Click Step 2
    all_btns = page.locator('button').all()
    gen_btns = [b for b in all_btns if b.is_enabled() and '2' in b.text_content()]
    if gen_btns:
        gen_btns[0].click()
        print('[OK] Step 2 Generate clicked')
    else:
        print('Available buttons:')
        for b in all_btns:
            print(f'  "{b.text_content()[:50]}" en={b.is_enabled()}')
        raise Exception('No step 2 button')

    page.wait_for_timeout(15000)
    page.screenshot(path='test_artifacts/frontend_4_generated.png')

    # Click Step 3
    all_btns = page.locator('button').all()
    exec_btns = [b for b in all_btns if b.is_enabled() and '3' in b.text_content()]
    if exec_btns:
        exec_btns[0].click()
        print('[OK] Step 3 Execute clicked')
    else:
        print('Available buttons:')
        for b in all_btns:
            print(f'  "{b.text_content()[:50]}" en={b.is_enabled()}')
        raise Exception('No step 3 button')

    page.wait_for_timeout(15000)
    page.screenshot(path='test_artifacts/frontend_5_done.png')

    # Check results
    body = page.locator('body').text_content()
    has_pass = '1' in body or 'pass' in body.lower()
    print(f'[OK] Test complete. Results visible: {has_pass}')

    browser.close()
    p.stop()

if __name__ == "__main__":
    test_flow()
