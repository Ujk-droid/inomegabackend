from pydantic import BaseModel


class CategoriesOut(BaseModel):
    category_1: list[str]
    category_2: list[str]


class UnitsOut(BaseModel):
    units: list[str]


class ParticularsOut(BaseModel):
    particulars: list[str]


class BankAccountsOut(BaseModel):
    bank_accounts: list[str]
