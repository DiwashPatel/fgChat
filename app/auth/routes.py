"""Password-based registration and session authentication routes."""

import re

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.auth import auth_bp
from app.extensions import db, limiter
from app.models import User

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,24}$")


def auth_page(mode: str):
    if current_user.is_authenticated:
        return redirect(url_for("chat.index"))
    return render_template("auth.html", mode=mode)


@auth_bp.get("/login")
def login():
    return auth_page("login")


@auth_bp.post("/login")
@limiter.limit("8 per minute")
def login_submit():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not 10 <= len(password) <= 128:
        flash("Those sign-in details didn't match an account.", "error")
        return render_template("auth.html", mode="login", username=username), 401
    user = db.session.scalar(db.select(User).where(func.lower(User.username) == username.lower()))
    if user is None or not user.check_password(password):
        flash("Those sign-in details didn't match an account.", "error")
        return render_template("auth.html", mode="login", username=username), 401
    login_user(user, remember=request.form.get("remember") == "on", fresh=True)
    return redirect(url_for("chat.index"))


@auth_bp.get("/register")
def register():
    return auth_page("register")


@auth_bp.post("/register")
@limiter.limit("5 per minute")
def register_submit():
    username = request.form.get("username", "").strip()
    display_name = request.form.get("display_name", "").strip()
    email = request.form.get("email", "").strip().lower() or None
    password = request.form.get("password", "")
    confirmation = request.form.get("confirm_password", "")
    errors = []
    if not USERNAME_PATTERN.fullmatch(username):
        errors.append("Choose a username with 3–24 letters, numbers, or underscores.")
    if not display_name or len(display_name) > 48:
        errors.append("Your display name must contain 1–48 characters.")
    if email and (len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)):
        errors.append("Enter a valid email address.")
    if not 10 <= len(password) <= 128:
        errors.append("Choose a password between 10 and 128 characters.")
    if password != confirmation:
        errors.append("The passwords do not match.")
    if errors:
        for error in errors:
            flash(error, "error")
        return render_template(
            "auth.html",
            mode="register",
            username=username,
            display_name=display_name,
            email=email or "",
        ), 400

    user = User(username=username, display_name=display_name, email=email)
    user.set_password(password)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("That username or email is already registered.", "error")
        return render_template(
            "auth.html",
            mode="register",
            username=username,
            display_name=display_name,
            email=email or "",
        ), 409
    login_user(user, fresh=True)
    return redirect(url_for("chat.index"))


@auth_bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
