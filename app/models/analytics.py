from pydantic import BaseModel


class AnalyticsResult(BaseModel):
    data: list[dict]
