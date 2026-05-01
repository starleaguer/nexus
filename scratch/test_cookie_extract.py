import browser_cookie3
import os

def get_naver_cookies():
    try:
        print("🔍 브라우저에서 네이버 쿠키를 찾는 중...")
        # Chrome, Edge, Firefox, Safari 순으로 시도
        cj = browser_cookie3.load(domain_name='.naver.com')
        
        nid_aut = ""
        nid_ses = ""
        
        for cookie in cj:
            if cookie.name == 'NID_AUT':
                nid_aut = cookie.value
            if cookie.name == 'NID_SES':
                nid_ses = cookie.value
                
        if nid_aut and nid_ses:
            print("✅ 쿠키를 성공적으로 찾았습니다!")
            print(f"NID_AUT: {nid_aut[:10]}...")
            print(f"NID_SES: {nid_ses[:10]}...")
            return nid_aut, nid_ses
        else:
            print("❌ 네이버 로그인 쿠키를 찾지 못했습니다. 브라우저에서 네이버에 로그인되어 있는지 확인해주세요.")
            return None, None
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        return None, None

if __name__ == "__main__":
    get_naver_cookies()
