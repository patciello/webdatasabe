from flask import Flask, render_template, redirect, url_for, session, request, flash
from pymongo import MongoClient
from authlib.integrations.flask_client import OAuth
from flask_mail import Mail, Message
import os
from dotenv import load_dotenv

app = Flask(__name__)
load_dotenv()

# Configurações do Flask
app.secret_key = os.environ.get('SECRET_KEY')

# Configuração do MongoDB
client = MongoClient(os.environ.get('MONGO_URI'))
db = client['webdatabase']
collection = db['webdata']

# Configuração do OAuth para Google Login
oauth = OAuth(app)
oauth.register(
    name='google',
    client_id=os.environ.get('CLIENT_ID'),
    client_secret=os.environ.get('CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

# Configuração do Flask-Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True
mail = Mail(app)

# Landing Page
@app.route('/')
def landing_page():
    if 'user_info' in session:
        return redirect(url_for('dashboard'))
    return render_template('landing_page.html')

# Login com Google
@app.route('/login')
def login():
    redirect_uri = url_for('authorize', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

# Autorização e obtenção de token
@app.route('/auth')
def authorize():
    token = oauth.google.authorize_access_token()
    user_info = oauth.google.parse_id_token(token)
    session['user_info'] = user_info

    user_email = user_info['email']
    user_data = db.users.find_one({'email': user_email})
    if not user_data:
        return redirect(url_for('setup'))
    else:
        session['columns'] = user_data['columns']
    return redirect(url_for('dashboard'))

# Configuração Inicial do Usuário
@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if request.method == 'POST':
        columns = request.form.getlist('column_names')
        columns = [col.strip() for col in columns if col.strip()]
        session['columns'] = columns
        user_email = session['user_info']['email']
        db.users.update_one(
            {'email': user_email},
            {'$set': {'columns': columns, 'shared_with_me': []}},
            upsert=True
        )
        return redirect(url_for('dashboard'))
    return render_template('setup.html')

# Dashboard com Cadastro e Pesquisa
@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    user_email = session['user_info']['email']
    user_collection = db[user_email]
    columns = session.get('columns', [])
    data = []

    if request.method == 'POST':
        form_data = {col: request.form.get(col) for col in columns}
        if all(form_data.values()):
            user_collection.insert_one(form_data)
            flash('Dados cadastrados com sucesso!', 'success')
            data = user_collection.find()
        else:
            search_query = {k: {'$regex': v, '$options': 'i'} for k, v in form_data.items() if v}
            data = user_collection.find(search_query)
    else:
        data = user_collection.find()

    return render_template('dashboard.html', data=data, columns=columns)

# Histórico de Cadastros
@app.route('/history')
def history():
    user_email = session['user_info']['email']
    user_collection = db[user_email]
    columns = session.get('columns', [])
    recent_data = user_collection.find().sort('_id', -1).limit(10)
    return render_template('history.html', data=recent_data, columns=columns)

# Compartilhamento de Coleções
@app.route('/share', methods=['POST'])
def share():
    user_email = session['user_info']['email']
    share_email = request.form['share_email']

    db.users.update_one(
        {'email': share_email},
        {'$addToSet': {'shared_with_me': user_email}},
        upsert=True
    )

    msg = Message('Convite para compartilhar coleção', sender=app.config['MAIL_USERNAME'], recipients=[share_email])
    msg.body = f'Você foi convidado por {user_email} para acessar a coleção de dados dele. Faça login para aceitar o convite.'
    mail.send(msg)

    flash('Convite enviado com sucesso!', 'success')
    return redirect(url_for('dashboard'))

# Visualização de Coleções Compartilhadas
@app.route('/shared')
def shared_collections():
    user_email = session['user_info']['email']
    user_data = db.users.find_one({'email': user_email})
    shared_with_me = user_data.get('shared_with_me', [])
    shared_data = {}

    for owner_email in shared_with_me:
        owner_collection = db[owner_email]
        data = owner_collection.find()
        owner_columns = db.users.find_one({'email': owner_email}).get('columns', [])
        shared_data[owner_email] = {'data': data, 'columns': owner_columns}

    return render_template('shared_collections.html', shared_data=shared_data)

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing_page'))

if __name__ == '__main__':
    app.run(debug=True)
