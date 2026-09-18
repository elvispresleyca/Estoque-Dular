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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Fallbacks para o Render encontrar a pasta templates
_candidates = [
    os.path.join(BASE_DIR, "templates"),
    os.path.join(os.getcwd(), "templates"),
    "/opt/render/project/src/templates",
]
_templates_dir = next((p for p in _candidates if os.path.isdir(p)), _candidates[0])
templates = Jinja2Templates(directory=_templates_dir)

_static_dir = os.path.join(os.path.dirname(_templates_dir), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
# ==================== INICIALIZAÇÃO ====================
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


# ==================== DASHBOARD ====================
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    products = db.query(models.Product).filter(models.Product.is_active == True).all()
    low_stock = []
    for p in products:
        total = get_stock_total(db, p.id)
        if total <= p.min_stock:
            low_stock.append({"product": p, "total": total})

    recent_movements = db.query(models.Movement).order_by(desc(models.Movement.created_at)).limit(10).all()

    active_reservations = db.query(models.Reservation).filter(
        models.Reservation.status == models.ReservationStatus.ativa
    ).order_by(desc(models.Reservation.created_at)).limit(10).all()

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    top_sellers = db.query(
        models.Product,
        func.sum(models.Movement.quantity).label("total_sold")
    ).join(models.Movement).filter(
        models.Movement.type == models.MovementType.saida,
        models.Movement.created_at >= thirty_days_ago
    ).group_by(models.Product.id).order_by(desc("total_sold")).limit(5).all()

    total_products = db.query(models.Product).filter(models.Product.is_active == True).count()
    total_depositos = db.query(models.Location).filter(
        models.Location.is_active == True,
        models.Location.type == models.LocationType.deposito
    ).count()
    total_lojas = db.query(models.Location).filter(
        models.Location.is_active == True,
        models.Location.type == models.LocationType.loja
    ).count()
    total_reservations = db.query(models.Reservation).filter(
        models.Reservation.status == models.ReservationStatus.ativa
    ).count()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "low_stock": low_stock,
        "recent_movements": recent_movements,
        "active_reservations": active_reservations,
        "top_sellers": top_sellers,
        "total_products": total_products,
        "total_depositos": total_depositos,
        "total_lojas": total_lojas,
        "total_reservations": total_reservations,
    })


# ==================== LOCAIS (Depósitos + Lojas) ====================
@app.get("/locais", response_class=HTMLResponse)
async def list_locations(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    depositos = db.query(models.Location).filter(
        models.Location.type == models.LocationType.deposito
    ).order_by(models.Location.name).all()
    lojas = db.query(models.Location).filter(
        models.Location.type == models.LocationType.loja
    ).order_by(models.Location.name).all()
    return templates.TemplateResponse("locais.html", {
        "request": request,
        "user": user,
        "depositos": depositos,
        "lojas": lojas,
    })


@app.get("/locais/novo", response_class=HTMLResponse)
async def new_location_form(request: Request, user=Depends(auth.require_admin)):
    return templates.TemplateResponse("local_form.html", {
        "request": request,
        "user": user,
        "location": None,
        "error": None
    })


@app.post("/locais/novo")
async def create_location(
    request: Request,
    name: str = Form(...),
    type: str = Form(...),
    address: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(auth.require_admin)
):
    existing = db.query(models.Location).filter(models.Location.name == name.strip()).first()
    if existing:
        return templates.TemplateResponse("local_form.html", {
            "request": request,
            "user": user,
            "location": None,
            "error": f"Já existe um local com o nome '{name}'"
        }, status_code=400)

    loc = models.Location(
        name=name.strip(),
        type=models.LocationType(type),
        address=address.strip() or None
    )
    db.add(loc)
    db.commit()

    # Cria estoque zero para todos os produtos neste novo local
    products = db.query(models.Product).filter(models.Product.is_active == True).all()
    for p in products:
        db.add(models.Stock(product_id=p.id, location_id=loc.id, quantity=0))
    db.commit()

    return RedirectResponse(url="/locais", status_code=302)


@app.get("/locais/{location_id}/editar", response_class=HTMLResponse)
async def edit_location_form(location_id: int, request: Request, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if not location:
        raise HTTPException(404, "Local não encontrado")
    return templates.TemplateResponse("local_form.html", {
        "request": request,
        "user": user,
        "location": location,
        "error": None
    })


@app.post("/locais/{location_id}/editar")
async def update_location(
    location_id: int,
    request: Request,
    name: str = Form(...),
    type: str = Form(...),
    address: str = Form(""),
    is_active: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user=Depends(auth.require_admin)
):
    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if not location:
        raise HTTPException(404, "Local não encontrado")

    existing = db.query(models.Location).filter(
        models.Location.name == name.strip(),
        models.Location.id != location_id
    ).first()
    if existing:
        return templates.TemplateResponse("local_form.html", {
            "request": request,
            "user": user,
            "location": location,
            "error": f"Já existe outro local com o nome '{name}'"
        }, status_code=400)

    location.name = name.strip()
    location.type = models.LocationType(type)
    location.address = address.strip() or None
    location.is_active = is_active == "on"
    db.commit()
    return RedirectResponse(url="/locais", status_code=302)


# ==================== PRODUTOS ====================
@app.get("/produtos", response_class=HTMLResponse)
async def list_products(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    products = db.query(models.Product).filter(models.Product.is_active == True).order_by(models.Product.name).all()
    locations = db.query(models.Location).filter(models.Location.is_active == True).order_by(
        models.Location.type, models.Location.name
    ).all()

    stocks_map = {}
    for p in products:
        stocks = db.query(models.Stock).filter(models.Stock.product_id == p.id).all()
        stocks_map[p.id] = {s.location_id: s.quantity for s in stocks}
        stocks_map[p.id]["total"] = get_stock_total(db, p.id)

    return templates.TemplateResponse("produtos.html", {
        "request": request,
        "user": user,
        "products": products,
        "stocks_map": stocks_map,
        "locations": locations,
    })


@app.get("/produtos/novo", response_class=HTMLResponse)
async def new_product_form(request: Request, user=Depends(auth.require_admin)):
    return templates.TemplateResponse("produto_form.html", {
        "request": request, "user": user, "product": None, "error": None
    })


@app.post("/produtos/novo")
async def create_product(
    request: Request,
    sku: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    unit: str = Form("un"),
    min_stock: int = Form(5),
    cost_price: float = Form(0.0),
    sale_price: float = Form(0.0),
    db: Session = Depends(get_db),
    user=Depends(auth.require_admin)
):
    if db.query(models.Product).filter(models.Product.sku == sku.strip().upper()).first():
        return templates.TemplateResponse("produto_form.html", {
            "request": request, "user": user, "product": None,
            "error": f"SKU '{sku}' já existe!"
        }, status_code=400)

    product = models.Product(
        sku=sku.strip().upper(),
        name=name.strip(),
        description=description.strip() or None,
        category=category.strip() or None,
        unit=unit,
        min_stock=min_stock,
        cost_price=cost_price,
        sale_price=sale_price
    )
    db.add(product)
    db.commit()

    locations = db.query(models.Location).all()
    for loc in locations:
        db.add(models.Stock(product_id=product.id, location_id=loc.id, quantity=0))
    db.commit()
    return RedirectResponse(url="/produtos", status_code=302)


@app.get("/produtos/{product_id}/editar", response_class=HTMLResponse)
async def edit_product_form(product_id: int, request: Request, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Produto não encontrado")
    return templates.TemplateResponse("produto_form.html", {
        "request": request, "user": user, "product": product, "error": None
    })


@app.post("/produtos/{product_id}/editar")
async def update_product(
    product_id: int,
    request: Request,
    sku: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    unit: str = Form("un"),
    min_stock: int = Form(5),
    cost_price: float = Form(0.0),
    sale_price: float = Form(0.0),
    db: Session = Depends(get_db),
    user=Depends(auth.require_admin)
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Produto não encontrado")

    existing = db.query(models.Product).filter(
        models.Product.sku == sku.strip().upper(),
        models.Product.id != product_id
    ).first()
    if existing:
        return templates.TemplateResponse("produto_form.html", {
            "request": request, "user": user, "product": product,
            "error": f"SKU '{sku}' já existe em outro produto!"
        }, status_code=400)

    product.sku = sku.strip().upper()
    product.name = name.strip()
    product.description = description.strip() or None
    product.category = category.strip() or None
    product.unit = unit
    product.min_stock = min_stock
    product.cost_price = cost_price
    product.sale_price = sale_price
    db.commit()
    return RedirectResponse(url="/produtos", status_code=302)


# ==================== MOVIMENTAÇÕES ====================
@app.get("/movimentacoes", response_class=HTMLResponse)
async def list_movements(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    movements = db.query(models.Movement).order_by(desc(models.Movement.created_at)).limit(100).all()
    return templates.TemplateResponse("movimentacoes.html", {
        "request": request, "user": user, "movements": movements
    })


@app.get("/movimentacoes/nova", response_class=HTMLResponse)
async def new_movement_form(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    products = db.query(models.Product).filter(models.Product.is_active == True).order_by(models.Product.name).all()
    locations = db.query(models.Location).filter(models.Location.is_active == True).order_by(
        models.Location.type, models.Location.name
    ).all()
    return templates.TemplateResponse("movimentacao_form.html", {
        "request": request, "user": user, "products": products, "locations": locations, "error": None
    })


@app.post("/movimentacoes/nova")
async def create_movement(
    request: Request,
    product_id: int = Form(...),
    location_id: int = Form(...),
    type: str = Form(...),
    quantity: int = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(auth.require_user)
):
    products = db.query(models.Product).filter(models.Product.is_active == True).order_by(models.Product.name).all()
    locations = db.query(models.Location).filter(models.Location.is_active == True).order_by(
        models.Location.type, models.Location.name
    ).all()

    if quantity <= 0:
        return templates.TemplateResponse("movimentacao_form.html", {
            "request": request, "user": user, "products": products, "locations": locations,
            "error": "Quantidade deve ser maior que zero"
        }, status_code=400)

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    location = db.query(models.Location).filter(models.Location.id == location_id).first()
    if not product or not location:
        raise HTTPException(400, "Produto ou local inválido")

    stock = get_or_create_stock(db, product_id, location_id)

    if type == "saida":
        available = get_available_stock(db, product_id, location_id)
        if quantity > available:
            return templates.TemplateResponse("movimentacao_form.html", {
                "request": request, "user": user, "products": products, "locations": locations,
                "error": f"Estoque insuficiente! Disponível: {available} (já considerando reservas)"
            }, status_code=400)
        stock.quantity -= quantity
    else:
        stock.quantity += quantity

    movement = models.Movement(
        product_id=product_id,
        location_id=location_id,
        user_id=user.id,
        type=models.MovementType(type),
        quantity=quantity,
        notes=notes.strip() or None
    )
    db.add(movement)
    db.commit()
    return RedirectResponse(url="/movimentacoes", status_code=302)


# ==================== TRANSFERÊNCIAS ====================
@app.get("/transferencias", response_class=HTMLResponse)
async def list_transfers(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    transfers = db.query(models.Movement).filter(
        models.Movement.type == models.MovementType.transferencia
    ).order_by(desc(models.Movement.created_at)).limit(100).all()
    return templates.TemplateResponse("transferencias.html", {
        "request": request, "user": user, "transfers": transfers
    })


@app.get("/transferencias/nova", response_class=HTMLResponse)
async def new_transfer_form(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    products = db.query(models.Product).filter(models.Product.is_active == True).order_by(models.Product.name).all()
    locations = db.query(models.Location).filter(models.Location.is_active == True).order_by(
        models.Location.type, models.Location.name
    ).all()
    return templates.TemplateResponse("transferencia_form.html", {
        "request": request, "user": user, "products": products, "locations": locations, "error": None
    })


@app.post("/transferencias/nova")
async def create_transfer(
    request: Request,
    product_id: int = Form(...),
    origin_id: int = Form(...),
    destination_id: int = Form(...),
    quantity: int = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(auth.require_user)
):
    products = db.query(models.Product).filter(models.Product.is_active == True).order_by(models.Product.name).all()
    locations = db.query(models.Location).filter(models.Location.is_active == True).order_by(
        models.Location.type, models.Location.name
    ).all()

    if origin_id == destination_id:
        return templates.TemplateResponse("transferencia_form.html", {
            "request": request, "user": user, "products": products, "locations": locations,
            "error": "Origem e destino devem ser diferentes"
        }, status_code=400)

    if quantity <= 0:
        return templates.TemplateResponse("transferencia_form.html", {
            "request": request, "user": user, "products": products, "locations": locations,
            "error": "Quantidade deve ser maior que zero"
        }, status_code=400)

    available = get_available_stock(db, product_id, origin_id)
    if quantity > available:
        return templates.TemplateResponse("transferencia_form.html", {
            "request": request, "user": user, "products": products, "locations": locations,
            "error": f"Estoque insuficiente na origem! Disponível: {available}"
        }, status_code=400)

    origin_stock = get_or_create_stock(db, product_id, origin_id)
    dest_stock = get_or_create_stock(db, product_id, destination_id)

    origin_stock.quantity -= quantity
    dest_stock.quantity += quantity

    origin = db.query(models.Location).filter(models.Location.id == origin_id).first()
    dest = db.query(models.Location).filter(models.Location.id == destination_id).first()

    movement = models.Movement(
        product_id=product_id,
        location_id=origin_id,
        destination_id=destination_id,
        user_id=user.id,
        type=models.MovementType.transferencia,
        quantity=quantity,
        notes=notes.strip() or f"Transferência: {origin.name} → {dest.name}"
    )
    db.add(movement)
    db.commit()
    return RedirectResponse(url="/transferencias", status_code=302)


# ==================== RESERVAS ====================
@app.get("/reservas", response_class=HTMLResponse)
async def list_reservations(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    reservations = db.query(models.Reservation).order_by(desc(models.Reservation.created_at)).limit(100).all()
    return templates.TemplateResponse("reservas.html", {
        "request": request, "user": user, "reservations": reservations
    })


@app.get("/reservas/nova", response_class=HTMLResponse)
async def new_reservation_form(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    products = db.query(models.Product).filter(models.Product.is_active == True).order_by(models.Product.name).all()
    locations = db.query(models.Location).filter(models.Location.is_active == True).order_by(
        models.Location.type, models.Location.name
    ).all()
    return templates.TemplateResponse("reserva_form.html", {
        "request": request, "user": user, "products": products, "locations": locations, "error": None
    })


@app.post("/reservas/nova")
async def create_reservation(
    request: Request,
    product_id: int = Form(...),
    location_id: int = Form(...),
    quantity: int = Form(...),
    customer_name: str = Form(...),
    customer_phone: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(auth.require_user)
):
    products = db.query(models.Product).filter(models.Product.is_active == True).order_by(models.Product.name).all()
    locations = db.query(models.Location).filter(models.Location.is_active == True).order_by(
        models.Location.type, models.Location.name
    ).all()

    if quantity <= 0:
        return templates.TemplateResponse("reserva_form.html", {
            "request": request, "user": user, "products": products, "locations": locations,
            "error": "Quantidade deve ser maior que zero"
        }, status_code=400)

    available = get_available_stock(db, product_id, location_id)
    if quantity > available:
        return templates.TemplateResponse("reserva_form.html", {
            "request": request, "user": user, "products": products, "locations": locations,
            "error": f"Estoque disponível insuficiente! Disponível: {available}"
        }, status_code=400)

    reservation = models.Reservation(
        product_id=product_id,
        location_id=location_id,
        salesperson_id=user.id,
        quantity=quantity,
        customer_name=customer_name.strip(),
        customer_phone=customer_phone.strip() or None,
        notes=notes.strip() or None,
        status=models.ReservationStatus.ativa,
        expires_at=datetime.utcnow() + timedelta(days=2)
    )
    db.add(reservation)
    db.commit()
    return RedirectResponse(url="/reservas", status_code=302)


@app.post("/reservas/{reservation_id}/confirmar")
async def confirm_reservation(reservation_id: int, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    reservation = db.query(models.Reservation).filter(models.Reservation.id == reservation_id).first()
    if not reservation or reservation.status != models.ReservationStatus.ativa:
        raise HTTPException(400, "Reserva inválida ou já processada")

    stock = get_or_create_stock(db, reservation.product_id, reservation.location_id)
    if stock.quantity < reservation.quantity:
        raise HTTPException(400, "Estoque físico insuficiente para confirmar")

    stock.quantity -= reservation.quantity

    movement = models.Movement(
        product_id=reservation.product_id,
        location_id=reservation.location_id,
        user_id=user.id,
        type=models.MovementType.saida,
        quantity=reservation.quantity,
        notes=f"Confirmação de reserva #{reservation.id} - Cliente: {reservation.customer_name}"
    )
    db.add(movement)
    reservation.status = models.ReservationStatus.confirmada
    db.commit()
    return RedirectResponse(url="/reservas", status_code=302)


@app.post("/reservas/{reservation_id}/cancelar")
async def cancel_reservation(reservation_id: int, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    reservation = db.query(models.Reservation).filter(models.Reservation.id == reservation_id).first()
    if not reservation or reservation.status != models.ReservationStatus.ativa:
        raise HTTPException(400, "Reserva inválida")
    reservation.status = models.ReservationStatus.cancelada
    db.commit()
    return RedirectResponse(url="/reservas", status_code=302)


# ==================== RELATÓRIOS ====================
@app.get("/relatorios", response_class=HTMLResponse)
async def reports(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    top_sellers = db.query(
        models.Product,
        func.sum(models.Movement.quantity).label("total_sold")
    ).join(models.Movement).filter(
        models.Movement.type == models.MovementType.saida,
        models.Movement.created_at >= thirty_days_ago
    ).group_by(models.Product.id).order_by(desc("total_sold")).limit(20).all()

    locations = db.query(models.Location).filter(models.Location.is_active == True).order_by(
        models.Location.type, models.Location.name
    ).all()
    stock_by_loc = {}
    for loc in locations:
        items = db.query(models.Stock, models.Product).join(models.Product).filter(
            models.Stock.location_id == loc.id,
            models.Stock.quantity > 0
        ).order_by(models.Product.name).all()
        stock_by_loc[loc.id] = items

    return templates.TemplateResponse("relatorios.html", {
        "request": request, "user": user,
        "top_sellers": top_sellers,
        "locations": locations,
        "stock_by_loc": stock_by_loc,
    })


# ==================== USUÁRIOS ====================
@app.get("/usuarios", response_class=HTMLResponse)
async def list_users(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    users = db.query(models.User).order_by(models.User.full_name).all()
    return templates.TemplateResponse("usuarios.html", {
        "request": request, "user": user, "users": users
    })


@app.get("/usuarios/novo", response_class=HTMLResponse)
async def new_user_form(request: Request, user=Depends(auth.require_admin)):
    return templates.TemplateResponse("usuario_form.html", {
        "request": request, "user": user, "error": None
    })


@app.post("/usuarios/novo")
async def create_user(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(auth.require_admin)
):
    if db.query(models.User).filter(models.User.username == username).first():
        return templates.TemplateResponse("usuario_form.html", {
            "request": request, "user": user, "error": "Nome de usuário já existe"
        }, status_code=400)

    new_user = models.User(
        username=username.strip().lower(),
        full_name=full_name.strip(),
        hashed_password=auth.get_password_hash(password),
        role=models.UserRole(role)
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/usuarios", status_code=302)
