"""Read an ordered catalog page and its total in one database snapshot."""

from sqlalchemy import func, select, true
from sqlalchemy.sql.selectable import CTE, Subquery


def ranked_catalog_page(ranked: CTE, offset: int, limit: int) -> Subquery:
    total = select(func.count().label("total")).select_from(ranked).cte()
    page = (
        select(ranked).where(ranked.c.position > offset, ranked.c.position <= offset + limit).cte()
    )
    return select(total.c.total, page).select_from(total).outerjoin(page, true()).subquery()
