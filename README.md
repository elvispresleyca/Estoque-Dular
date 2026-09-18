# Sistema de Gestão de Estoque - Depósitos & Lojas

Aplicativo web completo para gerenciar estoque com:

- Login e senha (acesso de qualquer lugar após publicar)
- **3 Depósitos + 3 Lojas (mostruários)** já cadastrados
- **Cadastro de novos depósitos e lojas**
- **Transferência** entre qualquer depósito e/ou loja
- Entrada e saída de mercadorias
- Alerta de estoque baixo
- Reserva de itens por vendedoras
- Ranking dos mais vendidos
- Relatórios por local
- Controle de usuários (admin e vendedora)

## Como rodar

```bash
cd estoque_app
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Acesse: **http://localhost:8000**

| Usuário | Senha    | Perfil     |
|---------|----------|------------|
| admin   | admin123 | Admin      |
| maria   | maria123 | Vendedora  |

## Publicar na internet

No **Render.com**:
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

## Locais iniciais

**Depósitos:** Central, Norte, Sul  
**Lojas (mostruários):** Centro, Norte, Sul  

Admin pode criar quantos depósitos e lojas quiser em **Depósitos & Lojas → Novo**.

## Transferências

Menu **Transferências** → escolha produto, origem e destino (qualquer combinação depósito↔loja).
