from fastapi import FastAPI, Depends, HTTPException, status, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from typing import Optional
import os

from . import models, database, auth
from .database import engine, get_db

# Cria as tabelas
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sistema de Estoque - Depósitos e Lojas", version="2.0")

templates = Jinja2Templates(directory="/opt/render/project/src/templates")
app.mount("/static", StaticFiles(directory="/opt/render/project/src/static"), name="static")

def init_data(db: Session):
    if db.query(models.User).count() == 0:
        admin = models.User(
            username="admin",
            full_name="Administrador",
            hashed_password=auth.get_password_hash("admin123"),
            role=models.UserRole.admin
        )
        db.add(admin)

        vend = models.User(
            username="maria",
            full_name="Maria Silva",
            hashed_password=auth.get_password_hash("maria123"),
            role=models.UserRole.vendedora
        )
        db.add(vend)

        # 3 Depósitos
        for nome, addr in [
            ("Depósito Central", "Rua Principal, 100"),
            ("Depósito Norte", "Av. Norte, 250"),
            ("Depósito Sul", "Rua Sul, 80"),
        ]:
            db.add(models.Location(name=nome, type=models.LocationType.deposito, address=addr))

        # 3 Lojas (mostruários)
        for nome, addr in [
            ("Loja Centro - Mostruário", "Shopping Centro, Loja 12"),
            ("Loja Norte - Mostruário", "Av. Norte, 500 - Térreo"),
            ("Loja Sul - Mostruário", "Rua das Flores, 33"),
        ]:
            db.add(models.Location(name=nome, type=models.LocationType.loja, address=addr))

        db.commit()
        print("✅ Dados iniciais criados!")
        print("   Login admin: admin / admin123")
        print("   Login vendedora: maria / maria123")


@app.on_event("startup")
def on_startup():
    db = database.SessionLocal()
    try:
        init_data(db)
    finally:
        db.close()


# ==================== HELPERS ====================
def get_stock_total(db: Session, product_id: int) -> int:
    result = db.query(func.sum(models.Stock.quantity)).filter(
        models.Stock.product_id == product_id
    ).scalar()
    return result or 0


def get_available_stock(db: Session, product_id: int, location_id: int) -> int:
    stock = db.query(models.Stock).filter(
        models.Stock.product_id == product_id,
        models.Stock.location_id == location_id
    ).first()
    physical = stock.quantity if stock else 0

    reserved = db.query(func.sum(models.Reservation.quantity)).filter(
        models.Reservation.product_id == product_id,
        models.Reservation.location_id == location_id,
        models.Reservation.status == models.ReservationStatus.ativa
    ).scalar() or 0

    return max(0, physical - reserved)


def get_or_create_stock(db: Session, product_id: int, location_id: int) -> models.Stock:
    stock = db.query(models.Stock).filter(
        models.Stock.product_id == product_id,
        models.Stock.location_id == location_id
    ).first()
    if not stock:
        stock = models.Stock(product_id=product_id, location_id=location_id, quantity=0)
        db.add(stock)
        db.flush()
    return stock


# ==================== AUTENTICAÇÃO ====================
@app.get("/", response_class=HTMLResponse)
async def root(request: Request, user=Depends(auth.get_current_user)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user=Depends(auth.get_current_user)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = auth.authenticate_user(db, username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Usuário ou senha incorretos"},
            status_code=400
        )
    access_token = auth.create_access_token(data={"sub": user.username})
    resp = RedirectResponse(url="/dashboard", status_code=302)
    resp.set_cookie(key="access_token", value=access_token, httponly=True, max_age=60*60*12, samesite="lax")
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp
