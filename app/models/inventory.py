from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Bulk template columns (Section 6, Screen 3) — adapted for the category_1/category_2
# split that Section 5.4.F introduces in place of the single free-text "category" column.
BULK_UPLOAD_COLUMNS = [
    "item_code",
    "item_name",
    "category_1",
    "category_2",
    "unit",
    "rate",
    "quantity_in_stock",
    "min_threshold",
]


class InventoryItemBase(BaseModel):
    item_code: str = Field(..., min_length=1, max_length=100)
    item_name: str = Field(..., min_length=1)
    category_1: str | None = None
    category_2: str | None = None
    unit: str = Field(..., min_length=1, max_length=20)
    rate: float = Field(..., gt=0)
    quantity_in_stock: int = Field(default=0, ge=0)
    min_threshold: int = Field(default=5, ge=0)

    @field_validator("item_code")
    @classmethod
    def normalize_item_code(cls, v: str) -> str:
        return v.strip().upper()


class InventoryItemCreate(InventoryItemBase):
    pass


class InventoryItemUpdate(BaseModel):
    item_name: str | None = None
    category_1: str | None = None
    category_2: str | None = None
    unit: str | None = None
    rate: float | None = Field(default=None, gt=0)
    quantity_in_stock: int | None = Field(default=None, ge=0)
    min_threshold: int | None = Field(default=None, ge=0)


class InventoryItemOut(BaseModel):
    id: str
    item_code: str
    item_name: str
    category_1: str | None = None
    category_2: str | None = None
    unit: str | None = None
    rate: float
    quantity_in_stock: int
    min_threshold: int
    is_low_stock: bool
    cloudinary_image_url: str | None = None
    cloudinary_public_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class InventoryListResponse(BaseModel):
    items: list[InventoryItemOut]
    total: int
    page: int
    page_size: int


class BulkUploadRowError(BaseModel):
    row: int
    item_code: str | None = None
    error: str


class BulkUploadPreviewRow(BaseModel):
    row: int
    item_code: str | None = None
    item_name: str | None = None
    status: str  # "insert" | "update" | "error"
    error: str | None = None


class BulkUploadResult(BaseModel):
    total_rows: int
    inserted: int
    updated: int
    skipped: int
    errors: list[BulkUploadRowError]
    preview_rows: list[BulkUploadPreviewRow] = []
    committed: bool = True
    images_matched: int = 0
    images_unmatched: int = 0
    # Diagnostic aid, always populated when an images_zip was sent (even on a
    # fully-successful match) — the raw entry names the zip reader actually
    # found and treated as images, capped the same way preview_rows is. Lets
    # a 0-matched result be debugged from the response alone: compare this
    # list's filenames (already stripped of any folder path) against the
    # item_code column in the uploaded spreadsheet.
    image_filenames_found: list[str] = []
