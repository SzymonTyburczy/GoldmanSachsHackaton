"""Query parameters shared by the paginated audit endpoints."""

from typing import Annotated

from fastapi import Query

MAX_EVENTS_PER_PAGE = 200

EventsAfter = Annotated[int, Query(ge=0, description="``next_after`` of the previous page")]
EventsLimit = Annotated[int, Query(ge=1, le=MAX_EVENTS_PER_PAGE)]
