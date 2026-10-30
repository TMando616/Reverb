"""publishing の業務ルールと認可（publishing design.md）。

HTTP のことは知らない（``fastapi`` は import しない）。外部 API の具体実装も知らず、
``ports.py`` の Protocol だけを受け取る（``.importlinter`` で強制）。
Service は flush までで、commit は呼び出し側（``get_session`` / ワーカー）が持つ。
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.channels.capabilities import CAPABILITIES, ChannelCode
from app.core.authorization import Actor, Permission, ProjectAuthorizer, require_not_demo
from app.core.crypto import TokenUnavailableError
from app.core.exceptions import (
    AppError,
    InvalidDraftError,
    InvalidQiitaTokenError,
    MisconfiguredError,
    NotFoundError,
    PublicationExistsError,
    QiitaItemMissingError,
    QiitaRateLimitedAppError,
    QiitaRejectedPublishError,
    QiitaTokenInvalidError,
    QiitaTokenMissingError,
    QiitaUnavailableAppError,
    UnsupportedChannelError,
    VersionConflictError,
)
from app.modules.publishing.models import (
    ChannelAccount,
    ChannelDraft,
    ConversionJob,
    JobStatus,
    Publication,
    Visibility,
)
from app.modules.publishing.ports import (
    ContentGateway,
    ConversionFailed,
    ConversionInput,
    ConversionOutput,
    JobDispatcher,
    ProfileSnapshot,
    QiitaAuthError,
    QiitaError,
    QiitaGateway,
    QiitaItemInput,
    QiitaNotFoundError,
    QiitaRateLimitedError,
    QiitaRejectedError,
    TokenCipherPort,
)
from app.modules.publishing.profiles import DEFAULT_PROFILES
from app.modules.publishing.repository import (
    ChannelAccountRepository,
    ChannelDraftRepository,
    ConversionJobRepository,
    ConversionProfileRepository,
    PublicationRepository,
)

logger = logging.getLogger("app.publishing")

# running のまま止まった行を回収するまでの時間。変換1回の締め切り（converter の
# CONVERSION_DEADLINE＝20分。SDK の再試行も含めた全体）より長くとり、生きている実行を
# 回収しない（design.md §7-3）。
STUCK_AFTER = timedelta(minutes=30)

# Qiita のタグ数（画面の制約。API ドキュメントに明記が無いので実機で確かめる・design.md §10-4）。
QIITA_MIN_TAGS = 1
QIITA_MAX_TAGS = 5


def qiita_app_error(exc: QiitaError) -> AppError:
    """Qiita のポート例外を HTTP のエラーコードに写す（design.md §10-5）。"""
    if isinstance(exc, QiitaAuthError):
        return QiitaTokenInvalidError()
    if isinstance(exc, QiitaNotFoundError):
        return QiitaItemMissingError()
    if isinstance(exc, QiitaRejectedError):
        return QiitaRejectedPublishError(str(exc))
    if isinstance(exc, QiitaRateLimitedError):
        return QiitaRateLimitedAppError()
    return QiitaUnavailableAppError()


class AccountService:
    """本人の外部トークンの登録・差し替え・削除（C5・design.md §5・§10-2）。

    企画の認可を通らない。対象は常に ``actor.user_id`` の行で、他人の行を指す引数を持たない。
    demo は書き込みだけ 403（閲覧は自分の「未登録」が見えるだけなので通す）。
    """

    def __init__(
        self, accounts: ChannelAccountRepository, qiita: QiitaGateway, cipher: TokenCipherPort
    ) -> None:
        self._accounts = accounts
        self._qiita = qiita
        self._cipher = cipher

    async def get_qiita(self, actor: Actor) -> ChannelAccount | None:
        return await self._accounts.get(actor.user_id, ChannelCode.QIITA)

    async def register_qiita(self, actor: Actor, token: str) -> ChannelAccount:
        """Qiita に問い合わせて有効なトークンだけを暗号化して保存する。"""
        require_not_demo(actor)
        # 鍵が無ければ Qiita に問い合わせる前に止める（保存できないトークンを確かめても無駄）。
        try:
            encrypted = self._cipher.encrypt(token)
        except TokenUnavailableError:
            logger.error("TOKEN_ENCRYPTION_KEYS is not set; cannot store qiita tokens")
            raise MisconfiguredError("token encryption is not configured") from None
        try:
            external_user_id = await self._qiita.authenticated_user(token)
        except (QiitaAuthError, QiitaRejectedError, QiitaNotFoundError):
            raise InvalidQiitaTokenError() from None
        except QiitaError as exc:
            raise qiita_app_error(exc) from None
        return await self._accounts.upsert(
            user_id=actor.user_id,
            channel=ChannelCode.QIITA,
            encrypted_token=encrypted,
            external_user_id=external_user_id,
        )

    async def delete_qiita(self, actor: Actor) -> None:
        require_not_demo(actor)
        await self._accounts.delete(actor.user_id, ChannelCode.QIITA)

    async def qiita_token_for(self, actor: Actor) -> str:
        """公開操作をした本人のトークンを復号して返す。他人のトークンでは投稿しない（§5）。"""
        account = await self._accounts.get(actor.user_id, ChannelCode.QIITA)
        if account is None:
            raise QiitaTokenMissingError()
        try:
            decrypted = self._cipher.decrypt(account.encrypted_token)
        except TokenUnavailableError:
            logger.warning("stored qiita token cannot be decrypted: user=%s", actor.user_id)
            raise QiitaTokenInvalidError() from None
        if decrypted.stale:
            await self._accounts.replace_token(account, self._cipher.encrypt(decrypted.plaintext))
        return decrypted.plaintext


def _apply_job(draft: ChannelDraft, job: ConversionJob) -> None:
    """変換結果で原稿を置き換える。手直しの印と保留中の結果は消える。"""
    draft.title = job.result_title or ""
    draft.body = job.result_body or ""
    draft.extra = job.result_extra or {}
    draft.source_revision_no = job.source_revision_no
    draft.applied_job_id = job.id
    draft.pending_job_id = None
    draft.edited_after_apply = False


# 原稿に入れるタグの形（schemas.DraftTag と同じ上限）。LLM の出力をそのまま入れると、
# 手で直さずに保存・投稿できない原稿になるため、反映するときにそろえる。
DRAFT_TAG_MAX_LENGTH = 50


def normalize_tags(tags: Sequence[str]) -> list[str]:
    """前後の空白を除き、空・長すぎるもの・重複を落として、Qiita の上限（5個）までにする。"""
    seen: list[str] = []
    for raw in tags:
        tag = str(raw).strip()
        if tag and len(tag) <= DRAFT_TAG_MAX_LENGTH and tag not in seen:
            seen.append(tag)
    return seen[:QIITA_MAX_TAGS]


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: int
    input: ConversionInput


class ConversionService:
    """チャネル変換の受付と、ワーカーからの結果の書き込み（C3・design.md §7・§9-2）。

    ``request`` / 照会は HTTP から、``claim`` / ``complete`` / ``fail`` / ``reap_stuck`` は
    ワーカーから呼ぶ。M2 でジョブ基盤に載せ替えても、このクラスは変えない（ADR-0017）。
    """

    def __init__(
        self,
        *,
        contents: ContentGateway,
        authz: ProjectAuthorizer,
        profiles: ConversionProfileRepository,
        jobs: ConversionJobRepository,
        drafts: ChannelDraftRepository,
        dispatcher: JobDispatcher,
        model: str,
    ) -> None:
        self._contents = contents
        self._authz = authz
        self._profiles = profiles
        self._jobs = jobs
        self._drafts = drafts
        self._dispatcher = dispatcher
        self._model = model

    async def request(
        self, actor: Actor, project_id: int, content_id: int, channel: ChannelCode
    ) -> ConversionJob:
        """変換を受け付けて ``queued`` の行を作る。実行はワーカー（202 で返す）。

        同じコンテンツ×チャネルで待機中・実行中があれば 409（部分 UNIQUE）。
        変換元は**今の最新リビジョン**で、ワーカーはその版の本文を変換する。
        """
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        content = await self._contents.get(actor, project_id, content_id)
        default = DEFAULT_PROFILES.get(channel)
        if default is None:
            raise UnsupportedChannelError(f"conversion to {channel} is not available yet")
        profile = await self._profiles.get_or_create(project_id, channel, default)
        snapshot = ProfileSnapshot(
            structure=profile.structure,
            tone=profile.tone,
            first_person=profile.first_person,
            banned_phrases=list(profile.banned_phrases),
        ).to_dict() | {"version": profile.version}
        job = await self._jobs.create(
            project_id=project_id,
            content_id=content.id,
            channel=channel,
            requested_by=actor.user_id,
            source_revision_no=await self._contents.latest_revision_no(content),
            profile_snapshot=snapshot,
            model=self._model,
        )
        await self._dispatcher.dispatch(job.id)
        return job

    async def list_jobs(
        self, actor: Actor, project_id: int, content_id: int
    ) -> Sequence[ConversionJob]:
        content = await self._contents.get(actor, project_id, content_id)
        return await self._jobs.list_for_content(content.id)

    async def get_job(
        self, actor: Actor, project_id: int, content_id: int, job_id: int
    ) -> ConversionJob:
        content = await self._contents.get(actor, project_id, content_id)
        job = await self._jobs.get_for_content(job_id, content.id)
        if job is None:
            raise NotFoundError("conversion")
        return job

    # --- ワーカーから呼ぶ（commit はワーカーが持つ） ---

    async def reap_stuck(self) -> int:
        now = datetime.now(UTC)
        reaped = await self._jobs.reap_stuck(now - STUCK_AFTER, now)
        if reaped:
            logger.warning("reaped %s stuck conversion job(s)", reaped)
        return reaped

    async def claim(self) -> ClaimedJob | None:
        """待機中を1件 ``running`` にし、変換の入力を組み立てて返す。

        ワーカーにはログインした人がいないので、**依頼した人として**認可を通し直す。
        依頼後にメンバーから外れた・コンテンツが消えた場合は、ここで失敗にする。
        """
        job = await self._jobs.claim_next(datetime.now(UTC))
        if job is None:
            return None
        requester = Actor(user_id=job.requested_by, is_demo=False)
        channel = ChannelCode(job.channel)
        try:
            await self._authz.require(requester, job.project_id, Permission.CONTENT_WRITE)
            revision = await self._contents.get_revision(
                requester, job.project_id, job.content_id, job.source_revision_no
            )
            existing_tags = await self._contents.tag_names(requester, job.project_id)
        except AppError as exc:
            await self._finish_failed(job, ConversionFailed("source_unavailable", exc.message))
            return None
        caps = CAPABILITIES[channel]
        return ClaimedJob(
            job_id=job.id,
            input=ConversionInput(
                channel_label=caps.label,
                format=caps.format,
                max_length=caps.max_length,
                title=revision.title,
                body_md=revision.body_md,
                profile=ProfileSnapshot.from_dict(job.profile_snapshot),
                existing_tags=list(existing_tags),
            ),
        )

    async def complete(self, job_id: int, output: ConversionOutput) -> None:
        """成功を書き、原稿へ反映する（design.md §9-2）。回収済みの行には書かない。"""
        job = await self._running_job(job_id)
        if job is None:
            return
        job.status = JobStatus.SUCCEEDED.value
        job.finished_at = datetime.now(UTC)
        job.result_title = output.title
        job.result_body = output.body
        job.result_extra = {"tags": normalize_tags(output.tags)}
        job.request_id = output.request_id
        job.input_tokens = output.input_tokens
        job.output_tokens = output.output_tokens
        await self._jobs.flush()
        await self._apply_to_draft(job)

    async def fail(self, job_id: int, failure: ConversionFailed) -> None:
        job = await self._running_job(job_id)
        if job is None:
            return
        await self._finish_failed(job, failure)

    async def _running_job(self, job_id: int) -> ConversionJob | None:
        job = await self._jobs.get(job_id)
        if job is None or job.status != JobStatus.RUNNING.value:
            # 回収（interrupted）された後に遅れて終わった実行。結果は捨てる。
            logger.warning("conversion job %s is no longer running; result dropped", job_id)
            return None
        return job

    async def _finish_failed(self, job: ConversionJob, failure: ConversionFailed) -> None:
        job.status = JobStatus.FAILED.value
        job.finished_at = datetime.now(UTC)
        job.error_code = failure.error_code
        job.error_message = failure.message
        job.request_id = failure.request_id
        await self._jobs.flush()
        logger.info(
            "conversion job %s failed: code=%s request_id=%s",
            job.id,
            failure.error_code,
            failure.request_id,
        )

    async def _apply_to_draft(self, job: ConversionJob) -> None:
        """変換後に手で直した原稿は置き換えず、保留にする（再変換で手直しを消さない）。"""
        channel = ChannelCode(job.channel)
        draft = await self._drafts.get(job.content_id, channel)
        title, body, extra = job.result_title or "", job.result_body or "", job.result_extra or {}
        if draft is None:
            await self._drafts.create(
                project_id=job.project_id,
                content_id=job.content_id,
                channel=channel,
                title=title,
                body=body,
                extra=extra,
                source_revision_no=job.source_revision_no,
                applied_job_id=job.id,
            )
            return
        if draft.edited_after_apply:
            draft.pending_job_id = job.id
        else:
            _apply_job(draft, job)
        await self._drafts.flush()


@dataclass(frozen=True, slots=True)
class ChannelView:
    """公開画面の1回分（design.md §6）。ジョブの状態を取り直すときも1リクエストで済ませる。"""

    channel: ChannelCode
    draft: ChannelDraft | None
    latest_job: ConversionJob | None
    pending_job: ConversionJob | None
    publication: Publication | None
    latest_revision_no: int

    @property
    def draft_is_stale(self) -> bool:
        """変換後に本文が更新された（design.md §9-3）。公開は止めない（警告のみ）。"""
        return self.draft is not None and self.draft.source_revision_no < self.latest_revision_no


class DraftService:
    """チャネル原稿の編集と、保留中の変換結果の採用（C4・design.md §9）。

    原稿の保存はリビジョンを作らない（原稿は作業台。履歴は変換ジョブの結果に残る）。
    """

    def __init__(
        self,
        *,
        contents: ContentGateway,
        authz: ProjectAuthorizer,
        drafts: ChannelDraftRepository,
        jobs: ConversionJobRepository,
        publications: PublicationRepository,
    ) -> None:
        self._contents = contents
        self._authz = authz
        self._drafts = drafts
        self._jobs = jobs
        self._publications = publications

    async def view(
        self, actor: Actor, project_id: int, content_id: int, channel: ChannelCode
    ) -> ChannelView:
        content = await self._contents.get(actor, project_id, content_id)
        draft = await self._drafts.get(content.id, channel)
        pending = None
        if draft is not None and draft.pending_job_id is not None:
            pending = await self._jobs.get_for_content(draft.pending_job_id, content.id)
        return ChannelView(
            channel=channel,
            draft=draft,
            latest_job=await self._jobs.latest_for(content.id, channel),
            pending_job=pending,
            publication=await self._publications.get_active(content.id, channel),
            latest_revision_no=await self._contents.latest_revision_no(content),
        )

    async def save(
        self,
        actor: Actor,
        project_id: int,
        content_id: int,
        channel: ChannelCode,
        *,
        title: str,
        body: str,
        tags: list[str],
        expected_version: int,
    ) -> ChannelDraft:
        """手で直した原稿を保存する。以後の再変換は、この原稿を置き換えず保留にする。"""
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        draft = await self._draft_for_update(actor, project_id, content_id, channel)
        _check_version(draft.version, expected_version)
        draft.title = title
        draft.body = body
        draft.extra = {**draft.extra, "tags": tags}
        draft.edited_after_apply = True
        draft.updated_by = actor.user_id
        await self._drafts.flush()
        return draft

    async def apply_pending(
        self,
        actor: Actor,
        project_id: int,
        content_id: int,
        channel: ChannelCode,
        *,
        job_id: int,
        expected_version: int,
    ) -> ChannelDraft:
        """保留中の変換結果で原稿を置き換える（design.md §9-2）。

        画面が見ていた保留中の結果（``job_id``）と今の保留中が違えば 409。
        その間に別の再変換が終わって、別の結果を見せずに置き換えるのを防ぐ。
        """
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        draft = await self._draft_for_update(actor, project_id, content_id, channel)
        _check_version(draft.version, expected_version)
        if draft.pending_job_id != job_id:
            raise VersionConflictError("the pending conversion result has changed")
        job = await self._jobs.get_for_content(job_id, draft.content_id)
        if job is None or job.status != JobStatus.SUCCEEDED.value:
            raise VersionConflictError("the pending conversion result has changed")
        _apply_job(draft, job)
        draft.updated_by = actor.user_id
        await self._drafts.flush()
        return draft

    async def _draft_for_update(
        self, actor: Actor, project_id: int, content_id: int, channel: ChannelCode
    ) -> ChannelDraft:
        content = await self._contents.get(actor, project_id, content_id)
        draft = await self._drafts.get(content.id, channel)
        if draft is None:
            # 原稿は変換から作る。変換していないチャネルの原稿は無い。
            raise NotFoundError("draft")
        return draft


def _check_version(current: int, expected: int) -> None:
    if current != expected:
        raise VersionConflictError()


@dataclass(frozen=True, slots=True)
class PublishedContent:
    """企画の公開済み一覧の1行（コンテンツ単位にまとめる・design.md §11）。"""

    content_id: int
    title: str
    publications: list[Publication]


class PublicationService:
    """外部への公開・更新・公開取消（C6・C8・design.md §10・§11）。

    公開系はすべて ``CONTENT_PUBLISH``（owner のみ）。同じコンテンツへの公開操作は
    コンテンツ行のロック（``lock_for_publish``）で直列化する。
    """

    def __init__(
        self,
        *,
        contents: ContentGateway,
        authz: ProjectAuthorizer,
        drafts: ChannelDraftRepository,
        publications: PublicationRepository,
        accounts: AccountService,
        qiita: QiitaGateway,
    ) -> None:
        self._contents = contents
        self._authz = authz
        self._drafts = drafts
        self._publications = publications
        self._accounts = accounts
        self._qiita = qiita

    async def publish_qiita(
        self,
        actor: Actor,
        project_id: int,
        content_id: int,
        *,
        visibility: Visibility,
        expected_draft_version: int,
    ) -> Publication:
        """Qiita へ新規投稿し、公開物を記録して公開済にする（design.md §10-3 の9段）。"""
        channel = ChannelCode.QIITA
        _require_auto(channel)
        # 2. 行ロック：2つ目の同時リクエストはここで1つ目の commit を待つ。
        content = await self._contents.lock_for_publish(actor, project_id, content_id)
        # 3. 外に送る前に状態を見る。送ってから弾くと記事だけが外に残る。
        self._contents.ensure_publishable(content)
        # 4.
        if await self._publications.get_active(content.id, channel) is not None:
            raise PublicationExistsError()
        # 5.
        draft = await self._draft(content.id, channel, expected_draft_version)
        item = _qiita_item(draft, private=visibility is Visibility.PRIVATE)
        # 6.
        token = await self._accounts.qiita_token_for(actor)
        # 7. 外部への送信。POST は冪等でないので再試行しない（QiitaClient）。
        try:
            ref = await self._qiita.create_item(token, item)
        except QiitaError as exc:
            raise qiita_app_error(exc) from None
        # 送信は成功した。以降で DB が失敗すると「Qiita にあるのに記録が無い」になるので、
        # 気づいて直せるよう外部 ID を残しておく（復旧手順は README）。
        logger.info("qiita item created: content=%s item=%s url=%s", content.id, ref.id, ref.url)
        try:
            # 8.
            publication = await self._publications.create(
                project_id=project_id,
                content_id=content.id,
                channel=channel,
                external_id=ref.id,
                url=ref.url,
                visibility=visibility.value,
                published_by=actor.user_id,
            )
            await self._contents.mark_published(actor, content)
        except Exception:
            logger.error(
                "qiita item %s (%s) was created but recording failed: content=%s",
                ref.id,
                ref.url,
                content.id,
            )
            raise
        return publication

    async def push_qiita(
        self,
        actor: Actor,
        project_id: int,
        content_id: int,
        *,
        expected_draft_version: int,
        visibility: Visibility | None = None,
    ) -> Publication:
        """公開済みの Qiita 記事を原稿で更新する。状態は変えない（design.md §10-3）。"""
        channel = ChannelCode.QIITA
        _require_auto(channel)
        content = await self._contents.lock_for_publish(actor, project_id, content_id)
        publication = await self._publications.get_active(content.id, channel)
        if publication is None:
            raise NotFoundError("publication")
        current = Visibility(publication.visibility or Visibility.PUBLIC.value)
        wanted = visibility or current
        if current is Visibility.PUBLIC and wanted is Visibility.PRIVATE:
            # 一般公開から限定共有には戻せない想定（実機で確かめる・design.md §10-4）。
            raise InvalidDraftError("a public item cannot be made private")
        draft = await self._draft(content.id, channel, expected_draft_version)
        item = _qiita_item(draft, private=wanted is Visibility.PRIVATE)
        token = await self._accounts.qiita_token_for(actor)
        try:
            ref = await self._qiita.update_item(token, publication.external_id, item)
        except QiitaError as exc:
            raise qiita_app_error(exc) from None
        publication.url = ref.url
        publication.visibility = wanted.value
        publication.last_pushed_at = datetime.now(UTC)
        await self._publications.flush()
        return publication

    async def cancel(self, actor: Actor, project_id: int, publication_id: int) -> None:
        """公開取消（論理削除）。外部の記事は消さない。0件になったら執筆中へ戻す（§11）。"""
        await self._authz.require(actor, project_id, Permission.CONTENT_PUBLISH)
        publication = await self._publications.get_in_project(publication_id, project_id)
        if publication is None or publication.cancelled_at is not None:
            raise NotFoundError("publication")
        # 同じコンテンツの公開と取消を直列化する。ロックを待つ間に別のリクエストが
        # 取り消しているかもしれないので、ロックを取ってから読み直して確かめる。
        content = await self._contents.lock_for_publish(actor, project_id, publication.content_id)
        await self._publications.reload(publication)
        if publication.cancelled_at is not None:
            raise NotFoundError("publication")
        publication.cancelled_at = datetime.now(UTC)
        publication.cancelled_by = actor.user_id
        await self._publications.flush()
        if await self._publications.count_active(content.id) == 0:
            await self._contents.mark_unpublished(actor, content)

    async def list_for_project(
        self, actor: Actor, project_id: int, *, content_id: int | None = None
    ) -> list[PublishedContent]:
        """``content_id`` を渡すと、そのコンテンツの公開物だけ（編集画面のバッジ用）。"""
        await self._authz.require(actor, project_id, Permission.CONTENT_VIEW)
        grouped: dict[int, PublishedContent] = {}
        rows = await self._publications.list_active_in_project(project_id, content_id=content_id)
        for publication, title in rows:
            # 新しい順に来るので、最初に出たコンテンツほど上に並ぶ。
            entry = grouped.setdefault(
                publication.content_id, PublishedContent(publication.content_id, title, [])
            )
            entry.publications.append(publication)
        return list(grouped.values())

    async def _draft(
        self, content_id: int, channel: ChannelCode, expected_version: int
    ) -> ChannelDraft:
        draft = await self._drafts.get(content_id, channel)
        if draft is None:
            raise NotFoundError("draft")
        _check_version(draft.version, expected_version)
        return draft


def _require_auto(channel: ChannelCode) -> None:
    """API で公開できるのは publish = auto のチャネルだけ（C1）。"""
    if CAPABILITIES[channel].publish != "auto":
        raise UnsupportedChannelError(f"{channel} cannot be published automatically")


def _qiita_item(draft: ChannelDraft, *, private: bool) -> QiitaItemInput:
    """原稿を Qiita の制約に照らして送る形にする（design.md §10-4）。満たさなければ 422。"""
    title = draft.title.strip()
    if not title:
        raise InvalidDraftError("title is required")
    if not draft.body.strip():
        raise InvalidDraftError("body is required")
    tags = list(
        dict.fromkeys(str(t).strip() for t in draft.extra.get("tags", []) if str(t).strip())
    )
    if not QIITA_MIN_TAGS <= len(tags) <= QIITA_MAX_TAGS:
        raise InvalidDraftError(f"qiita needs {QIITA_MIN_TAGS} to {QIITA_MAX_TAGS} tags")
    return QiitaItemInput(title=title, body=draft.body, tags=tags, private=private)
