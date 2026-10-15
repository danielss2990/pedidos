"""Catálogo: importação da planilha e casamento de itens extraídos com produtos."""

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models import Product, ProductSynonym
from app.services.extraction import ATTRIBUTE_KEYS, ItemExtraido
from app.services.text import normalize

CANDIDATE_LIMIT = 8


@dataclass
class Candidate:
    product: Product
    score: float


@dataclass
class MatchResult:
    product: Product | None
    confidence: float
    candidates: list[Candidate]


def _norm_value(value: Any) -> str:
    text = normalize(str(value)).replace(",", ".")
    for suffix in ("mm2", "mm", "a", "v", "w"):
        if text.endswith(suffix) and text[: -len(suffix)].strip().replace(".", "").isdigit():
            text = text[: -len(suffix)].strip()
    if text.replace(".", "", 1).isdigit() and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def build_search_text(product: Product, synonyms: list[str]) -> str:
    attrs = " ".join(str(v) for v in (product.atributos or {}).values())
    parts = [product.nome_tecnico, product.categoria or "", attrs, *synonyms]
    return normalize(" ".join(p for p in parts if p))


def attribute_score(wanted: dict[str, str], product_attrs: dict[str, Any]) -> float | None:
    """Fração dos atributos pedidos que o produto atende; None se algum conflita."""
    if not wanted:
        return 1.0
    hits = 0
    for key, value in wanted.items():
        if key not in product_attrs:
            continue
        if _norm_value(product_attrs[key]) != _norm_value(value):
            return None
        hits += 1
    return hits / len(wanted)


class Catalog:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings

    async def match(self, item: ItemExtraido) -> MatchResult:
        query = normalize(item.item_normalizado)
        text_score = func.greatest(
            func.word_similarity(query, Product.search_text),
            func.similarity(query, Product.search_text),
        )
        rows = (
            await self.session.execute(
                select(Product, text_score.label("score"))
                .where(Product.ativo.is_(True))
                .order_by(text_score.desc())
                .limit(CANDIDATE_LIMIT)
            )
        ).all()

        wanted = item.attrs()
        candidates: list[Candidate] = []
        for product, score in rows:
            attr = attribute_score(wanted, product.atributos or {})
            if attr is None:
                continue
            combined = float(score) if not wanted else 0.5 * float(score) + 0.5 * attr
            candidates.append(Candidate(product, round(combined, 4)))
        candidates.sort(key=lambda c: (-c.score, c.product.nome_tecnico))

        if not candidates:
            return MatchResult(None, 0.0, [])
        top = candidates[0]
        margin = top.score - candidates[1].score if len(candidates) > 1 else 1.0
        accepted = (
            top.score >= self.settings.match_confidence_threshold
            and margin >= self.settings.match_min_margin
        )
        return MatchResult(top.product if accepted else None, top.score, candidates)

    async def get_many(self, ids: list[str]) -> list[Product]:
        if not ids:
            return []
        uuids = [uuid.UUID(i) for i in ids]
        products = (await self.session.scalars(select(Product).where(Product.id.in_(uuids)))).all()
        by_id = {str(p.id): p for p in products}
        return [by_id[i] for i in ids if i in by_id]


def parse_price(raw: Any) -> Decimal:
    text = str(raw).replace("R$", "").strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"preço inválido: {raw!r}") from exc


def parse_attributes(raw: str | None) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for part in (raw or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key in ATTRIBUTE_KEYS and value.strip():
            attrs[key] = value.strip()
    return attrs


def _truthy(raw: Any) -> bool:
    return normalize(str(raw or "sim")) not in ("nao", "n", "false", "0", "inativo")


async def import_rows(session: AsyncSession, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Insere ou atualiza produtos a partir das linhas da planilha (colunas em minúsculo).

    Colunas: sku, nome_tecnico, categoria, unidade_venda, preco, shopify_variant_id,
    atributos ("bitola_mm2=2.5; cor=Azul"), sinonimos ("fio 2,5; fio de dois e meio"), ativo.
    """
    stats = {"criados": 0, "atualizados": 0, "ignorados": 0}
    existing = {
        p.sku: p
        for p in (
            await session.scalars(select(Product).options(selectinload(Product.synonyms)))
        ).all()
    }
    for row in rows:
        sku = str(row.get("sku") or "").strip()
        nome = str(row.get("nome_tecnico") or "").strip()
        if not sku or not nome or not str(row.get("preco") or "").strip():
            stats["ignorados"] += 1
            continue
        try:
            preco = parse_price(row["preco"])
        except ValueError:
            stats["ignorados"] += 1
            continue
        product = existing.get(sku)
        if product is None:
            product = Product(sku=sku, synonyms=[])
            session.add(product)
            existing[sku] = product
            stats["criados"] += 1
        else:
            stats["atualizados"] += 1
        product.nome_tecnico = nome
        product.categoria = str(row.get("categoria") or "").strip() or None
        product.unidade_venda = str(row.get("unidade_venda") or "unidades").strip()
        product.preco = preco
        product.shopify_variant_id = str(row.get("shopify_variant_id") or "").strip() or None
        product.atributos = parse_attributes(row.get("atributos"))
        product.ativo = _truthy(row.get("ativo"))

        terms = [t.strip() for t in str(row.get("sinonimos") or "").split(";") if t.strip()]
        learned = [s for s in product.synonyms if s.origem != "planilha"]
        product.synonyms = learned + [ProductSynonym(termo=t, origem="planilha") for t in terms]
        product.search_text = build_search_text(product, [s.termo for s in product.synonyms])
    await session.flush()
    return stats
