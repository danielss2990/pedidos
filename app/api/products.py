import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.deps import AdminUser, CurrentUser, QueueDep, SessionDep
from app.models import AuditLog, Product, ProductSynonym
from app.schemas import Page, ProductIn, ProductOut, ProductUpdate
from app.services.catalog import build_search_text
from app.services.text import normalize

router = APIRouter(prefix="/api/v1/products", tags=["catálogo"])


def _out(product: Product) -> ProductOut:
    out = ProductOut.model_validate(product)
    out.sinonimos = [s.termo for s in product.synonyms]
    return out


@router.get("", response_model=Page[ProductOut])
async def list_products(
    _: CurrentUser,
    session: SessionDep,
    q: str | None = None,
    ativo: bool | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> Page[ProductOut]:
    query = select(Product)
    if q:
        term = f"%{normalize(q)}%"
        query = query.where(or_(Product.search_text.ilike(term), Product.sku.ilike(f"%{q}%")))
    if ativo is not None:
        query = query.where(Product.ativo.is_(ativo))
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(
        query.options(selectinload(Product.synonyms))
        .order_by(Product.nome_tecnico)
        .limit(limit)
        .offset(offset)
    )
    return Page(items=[_out(p) for p in rows], total=total)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(data: ProductIn, admin: AdminUser, session: SessionDep) -> ProductOut:
    if await session.scalar(select(Product.id).where(Product.sku == data.sku)):
        raise HTTPException(status.HTTP_409_CONFLICT, "SKU já cadastrado")
    fields = data.model_dump(exclude={"sinonimos"})
    product = Product(
        **fields,
        synonyms=[ProductSynonym(termo=t, origem="painel") for t in data.sinonimos],
    )
    product.search_text = build_search_text(product, data.sinonimos)
    session.add(product)
    await session.flush()
    session.add(
        AuditLog(user_id=admin.id, acao="criar", entidade="product", entidade_id=str(product.id))
    )
    await session.commit()
    return _out(product)


@router.patch("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID, data: ProductUpdate, admin: AdminUser, session: SessionDep
) -> ProductOut:
    product = await session.scalar(
        select(Product).where(Product.id == product_id).options(selectinload(Product.synonyms))
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produto não encontrado")
    changes = data.model_dump(exclude_unset=True)
    sinonimos = changes.pop("sinonimos", None)
    for key, value in changes.items():
        setattr(product, key, value)
    if sinonimos is not None:
        product.synonyms = [ProductSynonym(termo=t, origem="painel") for t in sinonimos]
    product.search_text = build_search_text(product, [s.termo for s in product.synonyms])
    session.add(
        AuditLog(
            user_id=admin.id,
            acao="alterar",
            entidade="product",
            entidade_id=str(product.id),
            diff={k: str(v) for k, v in data.model_dump(exclude_unset=True).items()},
        )
    )
    await session.commit()
    return _out(product)


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_catalog(_: AdminUser, queue: QueueDep) -> dict[str, str]:
    await queue.enqueue_job("sync_catalog", _job_id="sync_catalog")
    return {"resultado": "sincronização agendada"}
