from datetime import date

from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.database import get_supabase
from app.dependencies import get_current_user
from app.models.analytics import AnalyticsResult
from app.services import analytics_service

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/monthly-sales-revenue", response_model=AnalyticsResult)
def monthly_sales_revenue(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    return analytics_service.monthly_sales_revenue(supabase, start_date, end_date)


@router.get("/top-selling-models", response_model=AnalyticsResult)
def top_selling_models(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    return analytics_service.top_selling_models(supabase, start_date, end_date)


@router.get("/customer-debt-balance", response_model=AnalyticsResult)
def customer_debt_balance(user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)):
    return analytics_service.customer_debt_balance(supabase)


@router.get("/low-stock-items", response_model=AnalyticsResult)
def low_stock_items(user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)):
    return analytics_service.low_stock_items(supabase)


@router.get("/payment-method-breakdown", response_model=AnalyticsResult)
def payment_method_breakdown(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    return analytics_service.payment_method_breakdown(supabase, start_date, end_date)


@router.get("/category-wise-sales", response_model=AnalyticsResult)
def category_wise_sales(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    return analytics_service.category_wise_sales(supabase, start_date, end_date)
