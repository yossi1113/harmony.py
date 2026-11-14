"""harmony.py の例外クラス."""


class HarmonyError(Exception):
    """すべての例外の基底クラス."""


class LoginFailure(HarmonyError):
    """トークンが無効でログインできない (401 / gateway close 4001・4004)."""


class HTTPError(HarmonyError):
    """REST API がエラーを返した."""

    def __init__(self, status: int, message: str = "", *, payload=None):
        self.status = status
        self.message = message or f"HTTP {status}"
        self.payload = payload
        super().__init__(f"{status}: {self.message}")


class Forbidden(HTTPError):
    """403: 権限がない / チャンネルが見えない."""


class NotFound(HTTPError):
    """404: 対象が存在しない."""


class RateLimited(HTTPError):
    """429: レート制限. retry_after は再試行までの秒数."""

    def __init__(self, status: int, message: str = "", *, payload=None, retry_after: float = 1.0):
        super().__init__(status, message, payload=payload)
        self.retry_after = retry_after


class NotSupportedError(HarmonyError):
    """Harmony Bot API にその操作のルート自体が存在しない.

    ライブラリ側の未実装ではなく、公式APIに手段がない操作
    (チャンネルのリネーム/削除、サーバーのリネームなど) で送出する。
    """


class InvalidArgument(HarmonyError):
    """引数が不正."""
