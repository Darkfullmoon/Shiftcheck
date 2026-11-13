from conftest import ADMIN_PW, USER_PW, Client, db_one


def test_login_failure_and_success(app):
    client = Client(app)
    assert client.login("admin", "wrong").status_code == 401
    response = client.login("admin", ADMIN_PW)
    assert response.status_code == 302 and response.headers["Location"].endswith("/dashboard")


def test_pages_require_login(app):
    client = Client(app)
    response = client.get("/audits")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_post_without_csrf_is_rejected(app):
    client = Client(app)
    client.refresh_token()
    response = client.c.post("/login", data={"username": "admin", "password": ADMIN_PW})
    assert response.status_code == 400


def test_logout_is_post_only(admin):
    assert admin.get("/logout").status_code == 405
    assert admin.post("/logout").status_code == 302
    assert admin.get("/dashboard").status_code == 302


def test_forced_password_change_flow(app, admin):
    admin.post("/admin/users", {"username": "newbie", "full_name": "New Bee", "role": "USER", "password": ""})
    with admin.c.session_transaction() as sess:
        temp = sess["reveal_password"]["password"]

    user = Client(app)
    response = user.login("newbie", temp)
    assert response.headers["Location"].endswith("/account/password")
    user.refresh_token()
    assert user.get("/dashboard").status_code == 302  # locked until the password changes
    weak = user.post("/account/password", {"current_password": temp, "new_password": "weak", "confirm_password": "weak"})
    assert weak.status_code == 200
    ok = user.post("/account/password", {"current_password": temp, "new_password": "Strong#Pass9",
                                         "confirm_password": "Strong#Pass9"})
    assert ok.status_code == 302
    assert user.get("/dashboard").status_code == 200
    assert db_one(app, "SELECT must_change_password FROM users WHERE username='newbie'")["must_change_password"] == 0


def test_users_cannot_open_admin_pages(nora):
    for url in ("/admin/users", "/admin/templates", "/admin/monitor", "/requests/queue", "/admin/settings"):
        assert nora.get(url).status_code == 403


def test_open_redirect_is_blocked(app):
    client = Client(app)
    client.refresh_token()
    response = client.c.post("/login?next=https://evil.example/", data={
        "username": "nora", "password": USER_PW, "csrf_token": client.token})
    assert response.headers["Location"].endswith("/dashboard")
