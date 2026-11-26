#!/usr/bin/env python3
"""카카오톡 '나에게 보내기' 알림.

GitHub Secrets
  KAKAO_REST_KEY        카카오 디벨로퍼스 앱의 REST API 키
  KAKAO_CLIENT_SECRET   (앱에서 클라이언트 시크릿을 켠 경우만)
  KAKAO_REFRESH_TOKEN   `python kakao.py connect` 가 자동으로 저장
  KAKAO_AUTH_CODE       연결할 때 한 번만 넣는 인가 코드 (또는 코드가 들어간 주소 전체)
  GH_PAT                Secrets 쓰기 권한이 있는 GitHub 토큰 (리프레시 토큰 자동 갱신용)

토큰 값은 화면·로그에 절대 출력하지 않습니다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

REDIRECT_URI = os.environ.get("KAKAO_REDIRECT_URI", "https://localhost")
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
TEXT_LIMIT = 200  # 카카오 텍스트 템플릿 글자 수 한도


class KakaoError(Exception):
    pass


def _mask(value: str) -> None:
    if value and os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{value}", flush=True)


def _post(url: str, data: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read())
            msg = err.get("error_description") or err.get("msg") or str(err)
        except Exception:
            msg = f"HTTP {e.code}"
        raise KakaoError(msg) from None


def _client() -> dict:
    key = os.environ.get("KAKAO_REST_KEY", "").strip()
    if not key:
        raise KakaoError("KAKAO_REST_KEY 가 없습니다")
    data = {"client_id": key}
    secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
    if secret:
        data["client_secret"] = secret
    return data


def save_refresh_token(token: str) -> bool:
    """GH_PAT 가 있으면 KAKAO_REFRESH_TOKEN 시크릿을 새 값으로 바꾼다."""
    pat, repo = os.environ.get("GH_PAT", "").strip(), os.environ.get("GITHUB_REPOSITORY", "")
    if not (pat and repo):
        return False
    r = subprocess.run(["gh", "secret", "set", "KAKAO_REFRESH_TOKEN", "--repo", repo],
                       input=token, text=True, capture_output=True, env={**os.environ, "GH_TOKEN": pat})
    if r.returncode != 0:
        print("리프레시 토큰 저장 실패: " + r.stderr.strip()[:200], file=sys.stderr)
        return False
    return True


def access_token() -> tuple[str, str]:
    """(access_token, 경고문). 리프레시 토큰이 새로 나오면 저장을 시도한다."""
    refresh = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if not refresh:
        raise KakaoError("KAKAO_REFRESH_TOKEN 이 없습니다 — '카카오 연결' 워크플로를 먼저 실행하세요")
    res = _post(TOKEN_URL, {"grant_type": "refresh_token", "refresh_token": refresh, **_client()})
    at = res.get("access_token")
    if not at:
        raise KakaoError("액세스 토큰을 받지 못했습니다")
    _mask(at)
    warn = ""
    new_rt = res.get("refresh_token")
    if new_rt:  # 만료 1개월 전부터 새 리프레시 토큰이 나온다
        _mask(new_rt)
        if not save_refresh_token(new_rt):
            warn = "카카오 연결이 한 달 안에 끊깁니다. '카카오 연결'을 다시 해 주세요."
    return at, warn


def send_text(token: str, text: str, url: str, button: str = "자세히 보기") -> None:
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT - 1] + "…"
    template = {"object_type": "text", "text": text,
                "link": {"web_url": url, "mobile_web_url": url}, "button_title": button}
    res = _post(MEMO_URL, {"template_object": json.dumps(template, ensure_ascii=False)}, token)
    if res.get("result_code") != 0:
        raise KakaoError(f"메시지 전송 실패: {res}")


def send_many(messages: list[tuple[str, str]]) -> str:
    """[(text, url), ...] 을 차례로 보낸다. 결과 한 줄을 돌려준다."""
    token, warn = access_token()
    if warn:
        messages = messages + [("⚠️ " + warn, "https://developers.kakao.com")]
    for text, url in messages:
        send_text(token, text, url)
    return f"카카오톡: {len(messages)}개 메시지 전송"


def connect() -> int:
    """KAKAO_AUTH_CODE(인가 코드) → 리프레시 토큰을 받아 시크릿에 저장하고 시험 메시지를 보낸다."""
    raw = os.environ.get("KAKAO_AUTH_CODE", "").strip()
    if "code=" in raw:
        raw = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query).get("code", [""])[0]
    if not raw:
        print("KAKAO_AUTH_CODE 시크릿이 비어 있습니다.", file=sys.stderr)
        return 2
    _mask(raw)
    try:
        res = _post(TOKEN_URL, {"grant_type": "authorization_code", "redirect_uri": REDIRECT_URI,
                                "code": raw, **_client()})
    except KakaoError as e:
        print(f"토큰 발급 실패: {e}\n(인가 코드는 몇 분 안에 만료되고 한 번만 쓸 수 있습니다. 새로 받아 다시 해 주세요.)",
              file=sys.stderr)
        return 1
    at, rt = res.get("access_token", ""), res.get("refresh_token", "")
    _mask(at)
    _mask(rt)
    if not rt:
        print("리프레시 토큰이 응답에 없습니다.", file=sys.stderr)
        return 1
    if not save_refresh_token(rt):
        print("GH_PAT 시크릿이 없거나 권한이 부족해 KAKAO_REFRESH_TOKEN 을 저장하지 못했습니다.", file=sys.stderr)
        return 1
    send_text(at, "✅ 나라장터 공고 알림이 카카오톡에 연결됐습니다.\n청주권 축산·급식 새 공고가 올라오면 평일 아침 7시 10분에 알려 드려요.",
              f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}")
    print("연결 완료: 리프레시 토큰 저장, 시험 메시지 전송. 이제 KAKAO_AUTH_CODE 시크릿은 지워도 됩니다.")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["connect"]:
        sys.exit(connect())
    print("사용법: python kakao.py connect", file=sys.stderr)
    sys.exit(2)
