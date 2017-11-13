from datetime import datetime
from pathlib import Path

import os
import twitter
from flask import Flask
from flask import g, session, request, url_for, flash
from flask import redirect, render_template
from flask_oauthlib.client import OAuth
from flask_sqlalchemy import SQLAlchemy
from mastodon import Mastodon
from mastodon.Mastodon import MastodonAPIError

from moa.forms import SettingsForm, MastodonIDForm
from moa.models import metadata, Bridge, MastodonHost, Settings

app = Flask(__name__)
config = os.environ.get('MOA_CONFIG', 'config.DevelopmentConfig')
app.config.from_object(config)

if app.config['SENTRY_DSN']:
    from raven.contrib.flask import Sentry
    sentry = Sentry(app, dsn=app.config['SENTRY_DSN'])

db = SQLAlchemy(metadata=metadata)
db.init_app(app)
oauth = OAuth(app)

twitter_oauth = oauth.remote_app(
    'twitter',
    consumer_key=app.config['TWITTER_CONSUMER_KEY'],
    consumer_secret=app.config['TWITTER_CONSUMER_SECRET'],
    base_url='https://api.twitter.com/1.1/',
    request_token_url='https://api.twitter.com/oauth/request_token',
    access_token_url='https://api.twitter.com/oauth/access_token',
    authorize_url='https://api.twitter.com/oauth/authorize'
)


@app.before_request
def before_request():
    g.t_user = None
    g.m_user = None

    if 'twitter' in session:
        g.t_user = session['twitter']

    if 'mastodon' in session:
        g.m_user = session['mastodon']

    # app.logger.info(session)


@app.route('/')
def index():
    mform = MastodonIDForm()
    settings = Settings()
    enabled = True
    found_settings = False

    if 'twitter' in session and 'mastodon' in session:
        # look up settings
        bridge = db.session.query(Bridge).filter_by(
            mastodon_user=session['mastodon']['username'],
            twitter_handle=session['twitter']['screen_name'],
        ).first()

        if bridge:
            found_settings = True
            settings = bridge.settings
            enabled = bridge.enabled
            app.logger.debug(f"Existing settings found: {enabled} {settings.__dict__}")

    form = SettingsForm(obj=settings)

    return render_template('index.html.j2',
                           form=form,
                           mform=mform,
                           enabled=enabled,
                           found_settings=found_settings
                           )


@app.route('/options', methods=["POST"])
def options():
    form = SettingsForm()

    if form.validate_on_submit():

        settings = Settings()

        form.populate_obj(settings)

        bridge_found = False

        bridge = db.session.query(Bridge).filter_by(
            mastodon_user=session['mastodon']['username'],
            twitter_handle=session['twitter']['screen_name'],
        ).first()

        if bridge:
            bridge_found = True
            app.logger.debug("Existing settings found")
        else:
            bridge = Bridge()

        bridge.enabled = form.enabled.data
        bridge.settings = settings
        bridge.updated = datetime.now()
        bridge.twitter_oauth_token = session['twitter']['oauth_token']
        bridge.twitter_oauth_secret = session['twitter']['oauth_token_secret']
        bridge.twitter_handle = session['twitter']['screen_name']
        bridge.mastodon_access_code = session['mastodon']['access_code']
        bridge.mastodon_user = session['mastodon']['username']
        bridge.mastodon_host = get_or_create_host(session['mastodon']['host'])

        # get twitter ID
        twitter_api = twitter.Api(
            consumer_key=app.config['TWITTER_CONSUMER_KEY'],
            consumer_secret=app.config['TWITTER_CONSUMER_SECRET'],
            access_token_key=session['twitter']['oauth_token'],
            access_token_secret=session['twitter']['oauth_token_secret'],
            tweet_mode='extended'  # Allow tweets longer than 140 raw characters
        )

        if not bridge_found:
            bridge.twitter_last_id = twitter_api.GetUserTimeline()[0].id

            # get mastodon ID
            api = mastodon_api(session['mastodon']['host'],
                               access_code=session['mastodon']['access_code'])

            bridge.mastodon_account_id = api.account_verify_credentials()["id"]

            try:
                statuses = api.account_statuses(bridge.mastodon_account_id)
                if len(statuses) > 0:
                    bridge.mastodon_last_id = statuses[0]["id"]
                else:
                    bridge.mastodon_last_id = 0

            except MastodonAPIError:
                bridge.mastodon_last_id = 0

        app.logger.debug("Saving new settings")

        if not bridge_found:
            db.session.add(bridge)

    flash("Settings Saved.")

    db.session.commit()

    return redirect(url_for('index'))


@app.route('/delete', methods=["POST"])
def delete():
    if 'twitter' in session and 'mastodon' in session:
        # look up settings
        bridge = db.session.query(Bridge).filter_by(
            mastodon_user=session['mastodon']['username'],
            twitter_handle=session['twitter']['screen_name'],
        ).first()

        if bridge:
            app.logger.info(f"Deleting settings for {session['mastodon']['username']} {session['twitter']['screen_name']}")
            db.session.delete(bridge)
            db.session.commit()

    return redirect(url_for('logout'))

# Twitter
#


@app.route('/twitter_login')
def twitter_login():
    callback_url = url_for('twitter_oauthorized', next=request.args.get('next'))

    app.logger.debug(callback_url)

    return twitter_oauth.authorize(callback=callback_url)


@app.route('/twitter_oauthorized')
def twitter_oauthorized():
    resp = twitter_oauth.authorized_response()
    if resp is None:
        flash('You denied the request to sign in.')
    else:
        session['twitter'] = resp

    return redirect(url_for('index'))


#
# Mastodon
#


def get_or_create_host(hostname):
    mastodonhost = db.session.query(MastodonHost).filter_by(hostname=hostname).first()

    if not mastodonhost:
        client_id, client_secret = Mastodon.create_app(
            "Moa",
            scopes=["read", "write"],
            api_base_url=f"https://{hostname}",
            website="https://moa.party/",
            redirect_uris=url_for("mastodon_oauthorized", _external=True)

        )
        app.logger.info(f"New host created for {hostname} {client_id} {client_secret}")

        mastodonhost = MastodonHost(hostname=hostname,
                                    client_id=client_id,
                                    client_secret=client_secret)
        db.session.add(mastodonhost)
        db.session.commit()

    app.logger.debug(f"Using Mastodon Host: {mastodonhost.hostname}")

    return mastodonhost


def mastodon_api(hostname, access_code=None):
    mastodonhost = get_or_create_host(hostname)

    api = Mastodon(
        client_id=mastodonhost.client_id,
        client_secret=mastodonhost.client_secret,
        api_base_url=f"https://{mastodonhost.hostname}",
        access_token=access_code,
        debug_requests=False
    )

    return api


@app.route('/mastodon_login', methods=['POST'])
def mastodon_login():
    form = MastodonIDForm()
    if form.validate_on_submit():

        user_id = form.mastodon_id.data

        if "@" not in user_id:
            flash('Invalid Mastodon ID')
            return redirect(url_for('index'))

        if user_id[0] == '@':
            user_id = user_id[1:]

        username, host = user_id.split('@')

        session['mastodon_host'] = host

        api = mastodon_api(host)

        return redirect(
            api.auth_request_url(
                scopes=['read', 'write'],
                redirect_uris=url_for("mastodon_oauthorized", _external=True)
            )
        )
    else:

        flash("Invalid Mastodon ID")
        return redirect(url_for('index'))


@app.route('/mastodon_oauthorized')
def mastodon_oauthorized():
    authorization_code = request.args.get('code')
    app.logger.info(f"Authorization code {authorization_code}")

    if authorization_code is None:
        flash('You denied the request to sign in to Mastodon.')
    else:

        host = session['mastodon_host']
        session.pop('mastodon_host', None)

        api = mastodon_api(host)

        access_code = api.log_in(
            code=authorization_code,
            scopes=["read", "write"],
            redirect_uri=url_for("mastodon_oauthorized", _external=True)
        )

        app.logger.info(f"Access code {access_code}")

        api.access_code = access_code

        session['mastodon'] = {
            'host': host,
            'access_code': access_code,
            'username': api.account_verify_credentials()["username"]
        }

    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.pop('twitter', None)
    session.pop('mastodon', None)
    return redirect(url_for('index'))


if __name__ == '__main__':

    app.run()
