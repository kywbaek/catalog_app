from flask import Flask, render_template, request, redirect, url_for
from flask import flash, jsonify

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Category, Item, User

from flask import session as login_session
import random
import string
import os
from functools import wraps

from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

app = Flask(__name__)

engine = create_engine('postgresql://catalog:catalog@localhost/catalog')
Base.metadata.bind = engine
DBSession = sessionmaker(bind=engine)
session = DBSession()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in login_session:
            flash("You must first be logged in")
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function


@app.route('/login')
def showLogin():
    """ create anti-forgery state token """
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    return render_template('login.html', STATE=state)


def createUser(login_session):
    """ User helper function """
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    """ User helper function """
    user = session.query(User).filter_by(id=user_id).first()
    return user


def getUserID(email):
    """ User helper function """
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None


@app.route('/gconnect', methods=['POST'])
def gconnect():
    """ sign in with google account """
    client_path = os.path.join(app.static_folder, 'g_client_secrets.json')
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets(client_path, scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    with open(client_path, 'r') as client_f:
	g_client_id = json.loads(client_f.read())['web']['client_id']
    if result['issued_to'] != g_client_id:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['provider'] = 'google'
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)
    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;'
    output += '-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("You are now logged in as %s" % login_session['username'])
    return output


@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    """ sign in with facebook account """
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    access_token = request.data
    print "access_token received %s" % access_token

    # Exchange client token for long-lived server-side token
    # with GET / oauth / access_token /
    id_path = os.path.join(app.static_folder, 'fb_client_secrets.json')
    with open(id_path, 'r') as id_f:
	app_id = json.loads(id_f.read())['web']['app_id']
    secret_path = os.path.join(app.static_folder, 'fb_client_secrets.json')
    with open(secret_path, 'r') as secret_f:
	app_secret = json.loads(secret_f.read())['web']['app_secret']

    url = 'https://graph.facebook.com/oauth/access_token?'
    url += 'grant_type=fb_exchange_token&client_id='
    url += '%s&client_secret=%s&fb_exchange_token=%s' % (
        app_id, app_secret, access_token)
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    # data = json.loads(result)

    # Use token to get user info from API
    userinfo_url = 'https://graph.facebook.com/v2.8/me'
    # get access token
    '''
      Due to the formatting for the result from the server token exchange
      we have to split the token first on commas and select the first index
      which gives us the key : value for the server access token then
      we split it on colons to pull out the actual token value and replace
      the remaining quotes with nothing so that it can be used directly
      in the graph api calls
  '''
    token = result.split(',')[0].split(':')[1].replace('"', '')

    url = 'https://graph.facebook.com/v2.8/me?access_token='
    url += '%s&fields=name,id,email' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    print "url sent for API access:%s" % url
    print "API JSON result: %s" % result
    data = json.loads(result)
    login_session['provider'] = 'facebook'
    login_session['username'] = data["name"]
    login_session['email'] = data["email"]
    login_session['facebook_id'] = data["id"]
    login_session['access_token'] = token

    # Get user picture
    url = 'https://graph.facebook.com/v2.8/me/picture?access_token='
    url += '%s&redirect=0&height=200&width=200' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    data = json.loads(result)

    login_session['picture'] = data["data"]["url"]

    # see if user exists
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;'
    output += '-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("You are now logged in as %s" % login_session['username'])
    return output


@app.route('/gdisconnect')
def gdisconnect():
    """ sign out from google account """
    access_token = login_session['access_token']
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    return result['status']


@app.route('/fbdisconnect')
def fbdisconnect():
    """ sign out from facebook account """
    facebook_id = login_session['facebook_id']
    access_token = login_session['access_token']
    url = 'https://graph.facebook.com/%s/permissions?access_token=%s' % (
        facebook_id, access_token)
    h = httplib2.Http()
    result = h.request(url, 'DELETE')[1]
    return result[1:-1]


@app.route('/disconnect')
def disconnect():
    """ log out from any account """
    if 'provider' in login_session:
        if login_session['provider'] == 'google':
            status_result = gdisconnect()
            if status_result != '200':
                response = make_response(json.dumps(
                    'Failed to revoke token for given user.', 400))
                response.headers['Content-Type'] = 'application/json'
                return response
            del login_session['gplus_id']
            del login_session['access_token']
        if login_session['provider'] == 'facebook':
            status_result = fbdisconnect()
            if status_result != '"success":true':
                response = make_response(json.dumps(
                    'Failed to revoke token for given user.', 400))
                response.headers['Content-Type'] = 'application/json'
                return response
            del login_session['facebook_id']

        del login_session['username']
        del login_session['email']
        del login_session['picture']
        del login_session['user_id']
        del login_session['provider']
        flash("You have successfully been logged out.")
        return redirect(url_for('showMain'))
    else:
        flash("You were not logged in to begin with!")
        redirect(url_for('showMain'))


@app.route('/')
def showMain():
    """ show main page for the application with categories and latest items """
    categories = session.query(Category).order_by(Category.name).all()
    latestItems = session.query(Item).order_by(Item.id.desc()).limit(10)
    return render_template('main.html',
                           categories=categories, latestItems=latestItems)


@app.route('/<path:category_name>/items')
def showItems(category_name):
    """ show items for the selected category """
    categories = session.query(Category).order_by(Category.name).all()
    curCategory = session.query(Category).filter_by(name=category_name).first()
    cat_id = curCategory.id
    items = session.query(Item).filter_by(cat_id=cat_id).all()
    num_items = session.query(Item).filter_by(cat_id=cat_id).count()
    return render_template('items.html',
                           categories=categories, items=items,
                           curCategory=curCategory, num_items=num_items)


@app.route('/<path:category_name>/<path:item_name>')
def showItem(category_name, item_name):
    """ show information about the selected item """
    curCategory = session.query(Category).filter_by(name=category_name).first()
    curItem = session.query(Item).filter_by(name=item_name).first()
    return render_template('item.html',
                           curItem=curItem, curCategory=curCategory)


@app.route('/<path:category_name>/<path:item_name>/edit',
           methods=['GET', 'POST'])
@login_required
def editItem(category_name, item_name):
    """ show web page where the selected item can be edited """
    categories = session.query(Category).order_by(Category.name).all()
    curCategory = session.query(Category).filter_by(name=category_name).first()
    cat_id = curCategory.id
    curItem = session.query(Item).filter_by(
        name=item_name, cat_id=cat_id).first()
    user_id = curItem.user_id
    if user_id != login_session['user_id']:
        flash("You are not authorized to edit {}".format(item_name))
        return redirect(url_for('showMain'))
    if request.method == 'POST':
        oldname = curItem.name
        if request.form['name']:
            curItem.name = request.form['name']
        if request.form['description']:
            curItem.description = request.form['description']
        if request.form['cat_name']:
            newCategory_name = request.form['cat_name']
            newCategory = session.query(Category).filter_by(
                name=newCategory_name).first()
            newCat_id = newCategory.id
            curItem.cat_id = newCat_id
        session.add(curItem)
        session.commit()
        flash("{} successfully edited!".format(oldname))
        return redirect(url_for('showMain'))
    return render_template('editItem.html',
                           curItem=curItem, curCategory=curCategory,
                           categories=categories)


@app.route('/<path:category_name>/<path:item_name>/delete',
           methods=['GET', 'POST'])
@login_required
def deleteItem(category_name, item_name):
    """ show web page where the selected item can be deleted """
    curCategory = session.query(Category).filter_by(name=category_name).first()
    cat_id = curCategory.id
    curItem = session.query(Item).filter_by(
        name=item_name, cat_id=cat_id).first()
    user_id = curItem.user_id
    if user_id != login_session['user_id']:
        flash("You are not authorized to delete {}".format(item_name))
        return redirect(url_for('showMain'))
    if request.method == 'POST':
        oldname = curItem.name
        session.delete(curItem)
        session.commit()
        flash("{} successfully deleted!".format(oldname))
        return redirect(url_for('showMain'))
    return render_template('deleteItem.html',
                           curItem=curItem, curCategory=curCategory)


@app.route('/items/new', methods=['GET', 'POST'])
@login_required
def newItem():
    """ show web page where a new item can be added """
    categories = session.query(Category).order_by(Category.name).all()
    if request.method == 'POST':
        if request.form['name'] and request.form['cat_name']:
            cat_name = request.form['cat_name']
            category = session.query(Category).filter_by(name=cat_name).first()
            cat_id = category.id
            if request.form['description']:
                description = request.form['description']
            else:
                description = ''
            newItem = Item(name=request.form['name'], description=description,
                           cat_id=cat_id, user_id=login_session['user_id'])
            session.add(newItem)
            session.commit()
            flash("{} successfully added!".format(newItem.name))
        return redirect(url_for('showMain'))
    return render_template('newItem.html', categories=categories)


@app.route('/catalog.json')
def catalogJSON():
    """ JSON endpoint for catalog """
    categories = session.query(Category).order_by(Category.id).all()
    items = session.query(Item).all()
    cat_list = [c.serialize for c in categories]
    item_list = [i.serialize for i in items]
    for cat in cat_list:
        for i in range(len(item_list)):
            item = item_list[0]
            if item['cat_id'] == cat['id']:
                if 'Item' not in cat:
                    cat['Item'] = [item]
                else:
                    cat['Item'] += [item]
                item_list.remove(item)
    return jsonify(Category=cat_list)


@app.route('/category.json')
def categoryJSON():
    categories = session.query(Category).order_by(Category.id).all()
    return jsonify(Category=[c.serialize for c in categories])


@app.route('/item.json')
def itemJSON():
    items = session.query(Item).all()
    return jsonify(Item=[i.serialize for i in items])


@app.route('/user.json')
def userJSON():
    users = session.query(User).all()
    return jsonify(User=[u.serialize for u in users])


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run()
