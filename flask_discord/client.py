from . import configs, _http, models

from flask import request, session, redirect
from oauthlib.common import add_params_to_uri


class DiscordOAuth2Session(_http.DiscordOAuth2HttpClient):
    """Main client class representing hypothetical OAuth2 session with discord.
    It uses Flask `session <http://flask.pocoo.org/docs/1.0/api/#flask.session>`_ local proxy object
    to save state, authorization token and keeps record of users sessions across different requests.
    This class inherits :py:class:`flask_discord._http.DiscordOAuth2HttpClient` class.

    Parameters
    ----------
    app : Flask
        An instance of your `flask application <http://flask.pocoo.org/docs/1.0/api/#flask.Flask>`_.
    client_id : int, optional
        The client ID of discord application provided. Can be also set to flask config
        with key ``DISCORD_CLIENT_ID``.
    client_secret : str, optional
        The client secret of discord application provided. Can be also set to flask config
        with key ``DISCORD_CLIENT_SECRET``.
    redirect_uri : str, optional
        The default URL to use to redirect user to after authorization. Can be also set to flask config
        with key ``DISCORD_REDIRECT_URI``.
    bot_token : str, optional
        The bot token of the application. This is required when you also need to access bot scope resources
        beyond the normal resources provided by the OAuth. Can be also set to flask config with
        key ``DISCORD_BOT_TOKEN``.
    users_cache : cachetools.LFUCache, optional
        Any dict like mapping to internally cache the authorized users. Preferably an instance of
        cachetools.LFUCache or cachetools.TTLCache. If not specified, default cachetools.LFUCache is used.
        Uses the default max limit for cache if ``DISCORD_USERS_CACHE_MAX_LIMIT`` isn't specified in app config.

    Attributes
    ----------
    client_id : int
        The client ID of discord application provided.
    redirect_uri : str
        The default URL to use to redirect user to after authorization.
    users_cache : cachetools.LFUCache
        A dict like mapping to internally cache the authorized users. Preferably an instance of
        cachetools.LFUCache or cachetools.TTLCache. If not specified, default cachetools.LFUCache is used.
        Uses the default max limit for cache if ``DISCORD_USERS_CACHE_MAX_LIMIT`` isn't specified in app config.

    """

    def create_session(self, scope: list = None, prompt: bool = True, params: dict = None):
        """Primary method used to create OAuth2 session and redirect users for
        authorization code grant.

        Parameters
        ----------
        scope : list, optional
            An optional list of valid `Discord OAuth2 Scopes
            <https://discordapp.com/developers/docs/topics/oauth2#shared-resources-oauth2-scopes>`_.
        prompt : bool, optional
            Determines if the OAuth2 grant should be explicitly prompted and re-approved. Defaults to True.
            Specify False for implicit grant which will skip the authorization screen and redirect to redirect URI.
        params : dict, optional
            An optional mapping of query parameters to supply to the authorization URL.

        Returns
        -------
        redirect
            Flask redirect to discord authorization servers to complete authorization code grant process.

        """
        scope = scope or request.args.get("scope", str()).split() or configs.DISCORD_OAUTH_DEFAULT_SCOPES

        if not prompt and set(scope) & set(configs.DISCORD_PASSTHROUGH_SCOPES):
            raise ValueError("You should use explicit OAuth grant for passthrough scopes like bot.")

        discord_session = self._make_session(scope=scope)
        authorization_url, state = discord_session.authorization_url(configs.DISCORD_AUTHORIZATION_BASE_URL)
        session["DISCORD_OAUTH2_STATE"] = state

        prompt = "consent" if prompt else "none"
        params = params or dict()
        params.update(prompt=prompt)
        authorization_url = add_params_to_uri(authorization_url, params)

        return redirect(authorization_url)

    def callback(self):
        """A method which should be always called after completing authorization code grant process
        usually in callback view.
        It fetches the authorization token and saves it flask
        `session <http://flask.pocoo.org/docs/1.0/api/#flask.session>`_ object.

        """
        if request.values.get("error"):
            return request.values["error"]
        discord = self._make_session(state=session.get("DISCORD_OAUTH2_STATE"))
        token = discord.fetch_token(
            configs.DISCORD_TOKEN_URL,
            client_secret=self.__client_secret,
            authorization_response=request.url
        )
        self._token_updater(token)

    def revoke(self):
        """This method clears current discord token, state and all session data from flask
        `session <http://flask.pocoo.org/docs/1.0/api/#flask.session>`_. Which means user will have
        to go through discord authorization token grant flow again. Also tries to remove the user from internal
        cache if they exist.

        """

        self.users_cache.pop(self.user_id, None)

        for session_key in self.SESSION_KEYS:
            try:
                session.pop(session_key)
            except KeyError:
                pass

    @property
    def authorized(self):
        """A boolean indicating whether current session has authorization token or not."""
        return self._make_session().authorized

    @staticmethod
    def fetch_user() -> models.User:
        """This method returns user object from the internal cache if it exists otherwise makes an API call to do so.

        Returns
        -------
        flask_discord.models.User

        """
        return models.User.get_from_cache() or models.User.fetch_from_api()

    @staticmethod
    def fetch_connections() -> list:
        """This method returns list of user connection objects from internal cache if it exists otherwise
        makes an API call to do so.

        Returns
        -------
        list
            List of :py:class:`flask_discord.models.UserConnection` objects.

        """
        user = models.User.get_from_cache()
        try:
            if user.connections is not None:
                return user.connections
        except AttributeError:
            pass

        return models.UserConnection.fetch_from_api()

    @staticmethod
    def fetch_guilds() -> list:
        """This method returns list of guild objects from internal cache if it exists otherwise makes an API
        call to do so.

        Returns
        -------
        list
            List of :py:class:`flask_discord.models.Guild` objects.

        """
        user = models.User.get_from_cache()
        try:
            if user.guilds is not None:
                return user.guilds
        except AttributeError:
            pass

        return models.Guild.fetch_from_api()
