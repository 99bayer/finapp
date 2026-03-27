from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os, json, hmac, hashlib

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "chave-secreta-troque-em-producao")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///finapp.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

KIWIFY_SECRET = os.environ.get("KIWIFY_SECRET", "")

# ── Models ──────────────────────────────────────────────────────────────────
class EmailAutorizado(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    email      = db.Column(db.String(150), unique=True, nullable=False)
    nome       = db.Column(db.String(100), nullable=True)
    plano      = db.Column(db.String(50), nullable=True)
    kiwify_id  = db.Column(db.String(100), nullable=True)
    autorizado = db.Column(db.Boolean, default=True)
    criado_em  = db.Column(db.DateTime, default=datetime.utcnow)

class Usuario(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(100), nullable=False)
    email      = db.Column(db.String(150), unique=True, nullable=False)
    senha_hash = db.Column(db.String(256), nullable=False)
    plano      = db.Column(db.String(20), default="ativo")
    criado_em  = db.Column(db.DateTime, default=datetime.utcnow)
    push_sub   = db.Column(db.Text, nullable=True)
    meses      = db.relationship("MesFinanceiro", backref="usuario", lazy=True,
                                  cascade="all, delete-orphan")

class MesFinanceiro(db.Model):
    id                = db.Column(db.Integer, primary_key=True)
    usuario_id        = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
    mes               = db.Column(db.String(7), nullable=False)
    criado_em         = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado        = db.Column(db.DateTime, default=datetime.utcnow)
    meta_nec          = db.Column(db.Float, default=0.50)
    meta_laz          = db.Column(db.Float, default=0.20)
    meta_inv          = db.Column(db.Float, default=0.20)
    meta_out          = db.Column(db.Float, default=0.10)
    meta_emerg        = db.Column(db.Integer, default=6)
    entradas_json     = db.Column(db.Text, default="[]")
    fixas_json        = db.Column(db.Text, default="[]")
    parcelas_json     = db.Column(db.Text, default="[]")
    variaveis_json    = db.Column(db.Text, default="[]")
    investimentos_json= db.Column(db.Text, default="[]")
    aportes_json      = db.Column(db.Text, default="[]")

    def to_dict(self):
        return {
            "id": self.id, "mes": self.mes,
            "meta_nec": self.meta_nec, "meta_laz": self.meta_laz,
            "meta_inv": self.meta_inv, "meta_out": self.meta_out,
            "meta_emerg": self.meta_emerg,
            "entradas":      json.loads(self.entradas_json or "[]"),
            "fixas":         json.loads(self.fixas_json or "[]"),
            "parcelas":      json.loads(self.parcelas_json or "[]"),
            "variaveis":     json.loads(self.variaveis_json or "[]"),
            "investimentos": json.loads(self.investimentos_json or "[]"),
            "aportes":       json.loads(self.aportes_json or "[]"),
        }

# ── Helpers ──────────────────────────────────────────────────────────────────
def usuario_logado():
    uid = session.get("usuario_id")
    if not uid: return None
    return db.session.get(Usuario, uid)

def mes_atual_str():
    return datetime.now().strftime("%Y-%m")

def nome_mes(mes_str):
    meses_pt = ["","Janeiro","Fevereiro","Março","Abril","Maio","Junho",
                "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
    try:
        y, m = mes_str.split("-")
        return f"{meses_pt[int(m)]} {y}"
    except:
        return mes_str

def get_or_create_mes(usuario_id, mes=None):
    mes = mes or mes_atual_str()
    m = MesFinanceiro.query.filter_by(usuario_id=usuario_id, mes=mes).first()
    if not m:
        m = MesFinanceiro(usuario_id=usuario_id, mes=mes)
        db.session.add(m); db.session.commit()
    return m

def email_autorizado(email):
    reg = EmailAutorizado.query.filter_by(email=email.lower().strip(), autorizado=True).first()
    return reg is not None

def calcular_dashboard(data):
    entradas  = data.get("entradas", [])
    fixas     = data.get("fixas", [])
    parcelas  = data.get("parcelas", [])
    variaveis = data.get("variaveis", [])
    invs      = data.get("investimentos", [])
    aportes   = data.get("aportes", [])

    total_rec  = sum(float(e.get("valor",0)) for e in entradas)
    total_fix  = sum(float(f.get("valor",0)) for f in fixas)
    total_parc = sum(float(p.get("valor_parcela",0)) for p in parcelas)
    total_var  = sum(float(v.get("valor",0)) for v in variaveis)
    total_apo  = sum(float(a.get("planejado",0)) for a in aportes if a.get("planejado"))
    total_pat  = sum(float(i.get("atual",0)) for i in invs)
    total_rend = sum(float(i.get("atual",0)) - float(i.get("aplicado",0))
                     for i in invs if i.get("atual") and i.get("aplicado"))
    total_saldo_dev = sum(float(p.get("faltam",0)) * float(p.get("valor_parcela",0))
                          for p in parcelas)
    total_gasto = total_fix + total_parc + total_var
    sobra = total_rec - total_gasto
    pct = lambda a,b: round(a/b*100,1) if b>0 else 0

    meta_nec = data.get("meta_nec", 0.5)
    meta_laz = data.get("meta_laz", 0.2)
    meta_inv = data.get("meta_inv", 0.2)
    meta_out = data.get("meta_out", 0.1)

    alertas = [
        {"icon":"🏠","label":"Comprometimento da renda","sub":"Fixas+Parcelas/Receita",
         "atual":pct(total_fix+total_parc,total_rec),"limite":meta_nec*100,
         "ok":(total_fix+total_parc)<=total_rec*meta_nec,"unidade":"%",
         "diag_ok":"Dentro do limite","diag_warn":"Acima do limite — revisar fixas"},
        {"icon":"🛒","label":"Lazer e variáveis","sub":"Variáveis/Receita",
         "atual":pct(total_var,total_rec),"limite":meta_laz*100,
         "ok":total_var<=total_rec*meta_laz,"unidade":"%",
         "diag_ok":"Lazer equilibrado","diag_warn":"Variáveis altos — cortar gastos"},
        {"icon":"📈","label":"Percentual investido","sub":"Aporte/Receita",
         "atual":pct(total_apo,total_rec),"limite":meta_inv*100,
         "ok":total_apo>=total_rec*meta_inv,"unidade":"%",
         "diag_ok":"Investindo o recomendado","diag_warn":"Aporte abaixo do ideal"},
        {"icon":"💳","label":"Parcelas vs renda","sub":"Parcelas/Receita",
         "atual":pct(total_parc,total_rec),"limite":30,
         "ok":total_parc<=total_rec*0.3,"unidade":"%",
         "diag_ok":"Parcelas controladas","diag_warn":"Parcelas comprometem a renda"},
        {"icon":"💰","label":"Sobra líquida","sub":"Sobra/Receita",
         "atual":pct(sobra,total_rec),"limite":10,
         "ok":sobra>=total_rec*0.1,"unidade":"%",
         "diag_ok":"Margem saudável","diag_warn":"Sobra muito baixa"},
    ]
    sobra_pos = max(0, sobra)
    projecao = []
    for i in range(5):
        saldo = max(0, total_saldo_dev - i*total_parc)
        sobra_proj = (total_rec-total_fix-total_var) if saldo==0 else sobra
        projecao.append({"mes":i,"saldo":round(saldo,2),"sobra":round(sobra_proj,2)})

    return {
        "total_rec":total_rec,"total_fix":total_fix,"total_parc":total_parc,
        "total_var":total_var,"total_gasto":total_gasto,"sobra":sobra,
        "total_pat":total_pat,"total_rend":round(total_rend,2),
        "total_apo":total_apo,"total_saldo_dev":total_saldo_dev,
        "alertas":alertas,"alertas_warn":sum(1 for a in alertas if not a["ok"]),
        "sobra_pos":sobra_pos,
        "sobra_reserva":round(sobra_pos*0.3,2),
        "sobra_investir":round(sobra_pos*0.5,2),
        "sobra_lazer":round(sobra_pos*0.2,2),
        "ganho_quit":round(total_parc,2),
        "sobra_pos_quit":round(total_rec-total_fix-total_var,2),
        "meta_nec":meta_nec,"meta_laz":meta_laz,"meta_inv":meta_inv,"meta_out":meta_out,
        "projecao":projecao,
        "pct_comp":pct(total_fix+total_parc,total_rec),
        "pct_sobra":pct(sobra,total_rec),
    }

# ── WEBHOOK KIWIFY ───────────────────────────────────────────────────────────
@app.route("/webhook/kiwify", methods=["POST"])
def webhook_kiwify():
    if False:  # validação desabilitada — Kiwify usa formato próprio
        sig = request.headers.get("X-Kiwify-Signature","")
        body = request.get_data()
        expected = hmac.new(KIWIFY_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return jsonify({"erro":"assinatura inválida"}), 401
    try:
        payload = request.get_json(force=True) or {}
        status  = payload.get("order_status","")
        evento  = payload.get("type", payload.get("event",""))
        status_validos = {"approved","paid","order_approved","order_paid",
                          "purchase.approved","purchase.paid"}
        if status not in status_validos and evento not in status_validos:
            return jsonify({"ok":True,"msg":"evento ignorado"}), 200

        customer  = payload.get("customer", payload.get("Customer",{}))
        email     = (customer.get("email") or payload.get("email") or
                     payload.get("customer_email","")).strip().lower()
        nome      = (customer.get("name") or customer.get("full_name") or
                     payload.get("customer_name","")).strip()
        plano     = (payload.get("product",{}).get("name") or
                     payload.get("plan_name") or payload.get("offer_name","Plano Padrão"))
        kiwify_id = str(payload.get("order_id") or payload.get("id",""))

        if not email:
            return jsonify({"erro":"e-mail não encontrado"}), 400

        existente = EmailAutorizado.query.filter_by(email=email).first()
        if existente:
            existente.autorizado = True; existente.plano = plano
        else:
            db.session.add(EmailAutorizado(email=email, nome=nome,
                                           plano=plano, kiwify_id=kiwify_id))
        db.session.commit()
        return jsonify({"ok":True,"email":email}), 200
    except Exception as e:
        return jsonify({"erro":str(e)}), 500

# ── ADMIN: liberar e-mail manualmente (para casos de suporte) ────────────────
@app.route("/admin/liberar", methods=["POST"])
def admin_liberar():
    ADMIN_KEY = os.environ.get("ADMIN_KEY","")
    if not ADMIN_KEY:
        return jsonify({"erro":"admin não configurado"}), 403
    payload = request.get_json() or {}
    if payload.get("key") != ADMIN_KEY:
        return jsonify({"erro":"chave incorreta"}), 403
    email = payload.get("email","").strip().lower()
    nome  = payload.get("nome","")
    plano = payload.get("plano","Manual")
    if not email:
        return jsonify({"erro":"e-mail obrigatório"}), 400
    ex = EmailAutorizado.query.filter_by(email=email).first()
    if ex:
        ex.autorizado = True
    else:
        db.session.add(EmailAutorizado(email=email, nome=nome,
                                       plano=plano, autorizado=True))
    db.session.commit()
    return jsonify({"ok":True,"email":email}), 200

@app.route("/admin/revogar", methods=["POST"])
def admin_revogar():
    ADMIN_KEY = os.environ.get("ADMIN_KEY","")
    if not ADMIN_KEY:
        return jsonify({"erro":"admin não configurado"}), 403
    payload = request.get_json() or {}
    if payload.get("key") != ADMIN_KEY:
        return jsonify({"erro":"chave incorreta"}), 403
    email = payload.get("email","").strip().lower()
    reg = EmailAutorizado.query.filter_by(email=email).first()
    if reg:
        reg.autorizado = False; db.session.commit()
        return jsonify({"ok":True,"revogado":email}), 200
    return jsonify({"erro":"e-mail não encontrado"}), 404

# ── Rotas ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if session.get("usuario_id"):
        return redirect(url_for("dashboard"))
    return render_template("landing.html")

@app.route("/cadastro", methods=["GET","POST"])
def cadastro():
    if request.method == "POST":
        nome  = request.form.get("nome","").strip()
        email = request.form.get("email","").strip().lower()
        senha = request.form.get("senha","")
        if not nome or not email or not senha:
            return render_template("cadastro.html", erro="Preencha todos os campos.")
        if len(senha) < 6:
            return render_template("cadastro.html", erro="Senha deve ter pelo menos 6 caracteres.")
        if not email_autorizado(email):
            return render_template("cadastro.html",
                erro="Este e-mail não possui acesso autorizado. "
                     "Use o mesmo e-mail da compra ou entre em contato pelo Instagram.")
        if Usuario.query.filter_by(email=email).first():
            return render_template("cadastro.html", erro="Este e-mail já possui uma conta. Faça login.")
        u = Usuario(nome=nome, email=email, senha_hash=generate_password_hash(senha))
        db.session.add(u); db.session.commit()
        session["usuario_id"] = u.id
        session["usuario_nome"] = u.nome
        return redirect(url_for("wizard", passo=1))
    return render_template("cadastro.html", erro=None)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        senha = request.form.get("senha","")
        u = Usuario.query.filter_by(email=email).first()
        if not u or not check_password_hash(u.senha_hash, senha):
            return render_template("login.html", erro="E-mail ou senha incorretos.")
        session["usuario_id"] = u.id
        session["usuario_nome"] = u.nome
        return redirect(url_for("dashboard"))
    return render_template("login.html", erro=None)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/wizard/<int:passo>")
def wizard(passo):
    u = usuario_logado()
    if not u: return redirect(url_for("login"))
    if passo < 1 or passo > 5: passo = 1
    mes = session.get("mes_ativo", mes_atual_str())
    m = get_or_create_mes(u.id, mes)
    data = m.to_dict()
    passos = [
        {"num":1,"icone":"💵","titulo":"Receitas","sub":"O que entrou no mês"},
        {"num":2,"icone":"🏠","titulo":"Saídas Fixas","sub":"O que você paga todo mês"},
        {"num":3,"icone":"💳","titulo":"Parcelamentos","sub":"Dívidas e parcelas"},
        {"num":4,"icone":"🛒","titulo":"Gastos Variáveis","sub":"Gastos do dia a dia"},
        {"num":5,"icone":"📈","titulo":"Investimentos","sub":"Sua carteira e aportes"},
    ]
    return render_template("wizard.html", passo=passo, passos=passos,
                           data=data, mes=mes, nome_mes=nome_mes(mes))

@app.route("/wizard/salvar", methods=["POST"])
def wizard_salvar():
    u = usuario_logado()
    if not u: return jsonify({"erro":"não autenticado"}), 401
    payload = request.get_json()
    mes = payload.get("mes", mes_atual_str())
    m = get_or_create_mes(u.id, mes)
    campo = payload.get("campo")
    valor = payload.get("valor")
    campos_validos = {
        "entradas":"entradas_json","fixas":"fixas_json","parcelas":"parcelas_json",
        "variaveis":"variaveis_json","investimentos":"investimentos_json","aportes":"aportes_json",
        "meta_nec":None,"meta_laz":None,"meta_inv":None,"meta_out":None,"meta_emerg":None,
    }
    if campo not in campos_validos:
        return jsonify({"erro":"campo inválido"}), 400
    if campo in ["meta_nec","meta_laz","meta_inv","meta_out"]:
        setattr(m, campo, float(valor))
    elif campo == "meta_emerg":
        m.meta_emerg = int(valor)
    else:
        setattr(m, campos_validos[campo], json.dumps(valor, ensure_ascii=False))
    m.atualizado = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok":True})

@app.route("/dashboard")
def dashboard():
    u = usuario_logado()
    if not u: return redirect(url_for("login"))
    mes = session.get("mes_ativo", mes_atual_str())
    m = get_or_create_mes(u.id, mes)
    data = m.to_dict()
    kpis = calcular_dashboard(data)
    historico = MesFinanceiro.query.filter_by(usuario_id=u.id)\
                .order_by(MesFinanceiro.mes.desc()).all()
    meses_lista = [{"mes":x.mes,"nome":nome_mes(x.mes)} for x in historico]
    return render_template("dashboard.html", u=u, data=data, kpis=kpis,
                           mes=mes, nome_mes=nome_mes(mes), meses_lista=meses_lista)

@app.route("/trocar-mes", methods=["POST"])
def trocar_mes():
    u = usuario_logado()
    if not u: return redirect(url_for("login"))
    session["mes_ativo"] = request.form.get("mes", mes_atual_str())
    return redirect(url_for("dashboard"))

@app.route("/novo-mes", methods=["POST"])
def novo_mes():
    u = usuario_logado()
    if not u: return redirect(url_for("login"))
    mes = request.form.get("mes")
    if mes:
        session["mes_ativo"] = mes
        get_or_create_mes(u.id, mes)
    return redirect(url_for("wizard", passo=1))

@app.route("/api/dashboard-data")
def api_dashboard_data():
    u = usuario_logado()
    if not u: return jsonify({"erro":"não autenticado"}), 401
    mes = session.get("mes_ativo", mes_atual_str())
    m = get_or_create_mes(u.id, mes)
    data = m.to_dict()
    kpis = calcular_dashboard(data)
    return jsonify({**data,**kpis,"nome":u.nome,"mes":mes,"nome_mes":nome_mes(mes)})

@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    u = usuario_logado()
    if not u: return jsonify({"erro":"não autenticado"}), 401
    u.push_sub = json.dumps(request.get_json())
    db.session.commit()
    return jsonify({"ok":True})

@app.route("/sw.js")
def service_worker():
    from flask import Response
    return Response(open("static/sw.js").read(), mimetype="application/javascript")

@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name":"Financeiro Pessoal","short_name":"Financeiro",
        "description":"Controle financeiro pessoal completo",
        "start_url":"/dashboard","display":"standalone",
        "background_color":"#005C2B","theme_color":"#005C2B",
        "orientation":"portrait",
        "icons":[
            {"src":"/static/icons/icon-192.png","sizes":"192x192","type":"image/png"},
            {"src":"/static/icons/icon-512.png","sizes":"512x512","type":"image/png"},
        ]
    })

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, port=5000)

# ── Esqueci minha senha ─────────────────────────────────────────────────────
import secrets
from datetime import timedelta

class TokenSenha(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
    token      = db.Column(db.String(100), unique=True, nullable=False)
    expira_em  = db.Column(db.DateTime, nullable=False)
    usado      = db.Column(db.Boolean, default=False)

def enviar_email_reset(destinatario, nome, link):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    GMAIL_USER = os.environ.get("GMAIL_USER", "")
    GMAIL_PASS = os.environ.get("GMAIL_PASS", "")

    if not GMAIL_USER or not GMAIL_PASS:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Redefinir sua senha — Financeiro Pessoal"
    msg["From"]    = GMAIL_USER
    msg["To"]      = destinatario

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px">
      <div style="background:#005C2B;padding:24px;border-radius:12px;text-align:center;margin-bottom:24px">
        <div style="font-size:2rem">💰</div>
        <div style="color:#fff;font-size:1.2rem;font-weight:800;margin-top:8px">Financeiro Pessoal</div>
      </div>
      <p style="color:#424242;font-size:1rem">Olá, <strong>{nome}</strong>!</p>
      <p style="color:#757575">Recebemos uma solicitação para redefinir sua senha. Clique no botão abaixo:</p>
      <div style="text-align:center;margin:28px 0">
        <a href="{link}" style="background:#005C2B;color:#fff;padding:14px 32px;
           border-radius:10px;text-decoration:none;font-weight:700;font-size:1rem">
          Redefinir minha senha
        </a>
      </div>
      <p style="color:#BDBDBD;font-size:.8rem;text-align:center">
        Este link expira em 1 hora. Se não foi você, ignore este e-mail.
      </p>
    </div>
    """

    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_PASS)
            smtp.sendmail(GMAIL_USER, destinatario, msg.as_string())
        return True
    except:
        return False

@app.route("/esqueci-senha", methods=["GET","POST"])
def esqueci_senha():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        u = Usuario.query.filter_by(email=email).first()
        # Sempre mostrar a mesma mensagem (segurança)
        msg = "Se este e-mail estiver cadastrado, você receberá o link em instantes."
        if u:
            token = secrets.token_urlsafe(32)
            expira = datetime.utcnow() + timedelta(hours=1)
            db.session.add(TokenSenha(usuario_id=u.id, token=token, expira_em=expira))
            db.session.commit()
            link = request.host_url + "redefinir-senha/" + token
            enviar_email_reset(u.email, u.nome, link)
        return render_template("esqueci_senha.html", msg=msg, erro=None)
    return render_template("esqueci_senha.html", msg=None, erro=None)

@app.route("/redefinir-senha/<token>", methods=["GET","POST"])
def redefinir_senha(token):
    tk = TokenSenha.query.filter_by(token=token, usado=False).first()
    if not tk or tk.expira_em < datetime.utcnow():
        return render_template("redefinir_senha.html",
            erro="Link inválido ou expirado. Solicite um novo.", token=None)
    if request.method == "POST":
        nova = request.form.get("senha","")
        conf = request.form.get("confirmar","")
        if len(nova) < 6:
            return render_template("redefinir_senha.html",
                erro="Senha deve ter pelo menos 6 caracteres.", token=token)
        if nova != conf:
            return render_template("redefinir_senha.html",
                erro="As senhas não coincidem.", token=token)
        u = db.session.get(Usuario, tk.usuario_id)
        u.senha_hash = generate_password_hash(nova)
        tk.usado = True
        db.session.commit()
        return render_template("redefinir_senha.html",
            erro=None, token=None, sucesso=True)
    return render_template("redefinir_senha.html", erro=None, token=token)
