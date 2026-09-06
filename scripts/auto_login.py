#!/usr/bin/env python3
"""Asistente de inicio de sesión para O2 Cloud España con Playwright.

Abre un navegador Chromium, introduce las credenciales proporcionadas (o las solicita),
y espera a que el usuario introduzca el código SMS de verificación que envía O2 al móvil.
Una vez autenticado, guarda la sesión de forma segura en el llavero/almacén local.
"""

import argparse
import getpass
import os
import sys
import time

from playwright.sync_api import sync_playwright
from o2cloud.config import AppConfig
from o2cloud.secrets import SecretStore
from o2cloud.auth.oidc import _persist, extract_validation_key, extract_cookie_header
from o2cloud.auth.browser import _cookies_to_header


def main() -> None:
    parser = argparse.ArgumentParser(description="Login asistido para O2 Cloud España")
    parser.add_argument("--email", "-e", help="Email o usuario de Mi O2 (también vía env O2_EMAIL)")
    parser.add_argument("--password", "-p", help="Contraseña (también vía env O2_PASSWORD)")
    parser.add_argument("--profile", default="default", help="Perfil de configuración (default: default)")
    parser.add_argument("--timeout", type=int, default=300, help="Tiempo máximo de espera en segundos (default: 300)")
    args = parser.parse_args()

    email = args.email or os.environ.get("O2_EMAIL")
    password = args.password or os.environ.get("O2_PASSWORD")

    if not email:
        email = input("Introduce tu email o teléfono de O2: ").strip()
    if not password:
        password = getpass.getpass("Introduce tu contraseña de O2: ")

    config = AppConfig()
    secret_store = SecretStore(args.profile)

    print("\nAbriendo navegador para iniciar sesión...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            page.goto(f"{config.base_url.rstrip('/')}/login", timeout=60000)
            page.wait_for_timeout(2000)

            # Aceptar cookies si aparece el banner
            cookie_btn = page.query_selector("button:has-text('Aceptar todas las cookies')")
            if cookie_btn:
                try:
                    cookie_btn.click()
                    page.wait_for_timeout(1000)
                except Exception:
                    pass

            # Seleccionar inicio de sesión con email y contraseña
            email_link = page.query_selector("text='Inicia sesión con email y contraseña'")
            if email_link:
                try:
                    email_link.click()
                    page.wait_for_timeout(2000)
                except Exception:
                    pass

            # Rellenar credenciales
            user_input = page.query_selector("input[name='username']")
            if user_input:
                user_input.fill(email)
                page.wait_for_timeout(400)

            pass_input = page.query_selector("input[name='password']")
            if pass_input:
                pass_input.fill(password)
                page.wait_for_timeout(400)

            rem_input = page.query_selector("input[name='rememberMe']")
            if rem_input and not rem_input.is_checked():
                try:
                    rem_input.check()
                except Exception:
                    pass

            # Enviar formulario
            submit_btn = page.query_selector("button:has-text('Acceder')")
            if submit_btn:
                print("Enviando credenciales...")
                submit_btn.click()

            print("\n" + "=" * 60)
            print("Esperando verificación SMS.")
            print("Revisa tu móvil e introduce el código SMS en la ventana del navegador.")
            print("=" * 60 + "\n")

            deadline = time.time() + args.timeout
            captured = False
            while time.time() < deadline:
                try:
                    cookies = context.cookies()
                    header = _cookies_to_header(cookies, host="cloud.o2online.es")
                    if header:
                        print("¡Sesión capturada con éxito!")
                        key = extract_validation_key(header)
                        full_header = extract_cookie_header(header)
                        _persist(config, secret_store, key, cookie=full_header, profile=args.profile)
                        print("Sesión guardada en el sistema.")
                        captured = True
                        break
                except Exception as e:
                    pass
                time.sleep(1)

            page.wait_for_timeout(2000)
        finally:
            browser.close()

        if not captured:
            print("Error: Tiempo de espera agotado sin detectar sesión.")
            sys.exit(1)
        else:
            print("Login completado correctamente. Ya puedes sincronizar tus archivos.")
            sys.exit(0)


if __name__ == "__main__":
    main()
