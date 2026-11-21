from flask import flash, g, redirect, render_template, request, url_for

from ..db import get_db
from ..security import (burn_password_check, hash_password, is_staff, limiter, login_user, logout_user,
                        password_problem, rate_limit, staff_required, verify_password)
from ..util import clean, safe_next
from . import bp


@bp.route("/login", methods=["GET", "POST"])
@rate_limit("admin-login-ip", 20, 600)
def login():
    if is_staff(g.user):
        return redirect(url_for("admin.dashboard"))
    error = None
    nxt = safe_next(request.args.get("next") or request.form.get("next"), url_for("admin.dashboard"))
    if request.method == "POST":
        email = clean(request.form.get("email"), 254).lower()
        pw = request.form.get("password", "")
        key = f"admin-login-email:{email}"
        db = get_db()
        if limiter.blocked(key, 5, 900):
            error = "Too many failed attempts. Please wait 15 minutes."
        else:
            user = db.execute(
                "SELECT u.*, r.permissions FROM users u JOIN roles r ON r.id=u.role_id WHERE u.email=? AND u.is_active=1",
                (email,)).fetchone()
            if user and verify_password(user["password_hash"], pw) and user["permissions"]:
                limiter.reset(key)
                login_user(user["id"])
                return redirect(nxt)
            if not user:
                burn_password_check()
            limiter.hit(key, 900)
            error = "Incorrect email or password."
    return render_template("admin/login.html", error=error, next=nxt), (401 if error else 200)


@bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("admin.login"))


@bp.route("/account", methods=["GET", "POST"])
@staff_required()
@rate_limit("admin-password", 10, 900)
def my_account():
    if request.method == "POST":
        cur, new = request.form.get("current", ""), request.form.get("password", "")
        if not verify_password(g.user["password_hash"], cur):
            flash("Your current password is incorrect.", "error")
        elif (p := password_problem(new)):
            flash(p, "error")
        elif new != request.form.get("password2"):
            flash("New passwords don't match.", "error")
        else:
            get_db().execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), g.user["id"]))
            flash("Password changed.", "success")
        return redirect(url_for("admin.my_account"))
    return render_template("admin/account.html")
