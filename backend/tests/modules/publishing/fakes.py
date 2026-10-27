"""publishing のポートの fake（publishing design.md §15・C10）。実際の外部 API は呼ばない。"""

from dataclasses import dataclass, field

from app.modules.publishing.ports import QiitaError, QiitaItemInput, QiitaItemRef


@dataclass
class FakeQiita:
    """呼ばれた内容を記録し、``fail_with`` を設定すると次の呼び出しでそれを投げる。"""

    user_name: str = "t_mando_"
    fail_with: QiitaError | None = None
    created: list[tuple[str, QiitaItemInput]] = field(default_factory=list)
    updated: list[tuple[str, str, QiitaItemInput]] = field(default_factory=list)
    tokens_seen: list[str] = field(default_factory=list)
    _next_id: int = 1

    def _maybe_fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    async def authenticated_user(self, token: str) -> str:
        self.tokens_seen.append(token)
        self._maybe_fail()
        return self.user_name

    async def create_item(self, token: str, item: QiitaItemInput) -> QiitaItemRef:
        self.tokens_seen.append(token)
        self._maybe_fail()
        item_id = f"item{self._next_id:04d}"
        self._next_id += 1
        self.created.append((token, item))
        return QiitaItemRef(id=item_id, url=f"https://qiita.com/{self.user_name}/items/{item_id}")

    async def update_item(self, token: str, item_id: str, item: QiitaItemInput) -> QiitaItemRef:
        self.tokens_seen.append(token)
        self._maybe_fail()
        self.updated.append((token, item_id, item))
        return QiitaItemRef(id=item_id, url=f"https://qiita.com/{self.user_name}/items/{item_id}")
