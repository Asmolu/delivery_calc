from pydantic import BaseModel, Field
from typing import List, Optional


class QuoteItem(BaseModel):
    category: str
    subtype: str
    quantity: int


class QuoteRequest(BaseModel):
    upload_lat: float
    upload_lon: float
    transport_type: str
    forbidden_types: list[str] = []
    items: List[QuoteItem]

    add_manipulator: bool = Field(False, alias="addManipulator")
    selected_special: Optional[str] = Field(None, alias="selectedSpecial")

    # Новый этап: выбор транспорта доставки/разгрузки
    delivery_transport_tag: str = Field("auto", alias="deliveryTransportTag")
    unloading_transport_tag: str = Field("auto", alias="unloadingTransportTag")
