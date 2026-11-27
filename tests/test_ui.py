"""Test de l'interface dans un vrai navigateur (Chrome via Playwright). Ignoré si indisponible.
Le réseau externe est bloqué : l'interface doit fonctionner avec le plan schématique SVG."""

import os
import shutil

import pytest

playwright = pytest.importorskip("playwright.sync_api")
CHROME = os.environ.get("CHROME_PATH") or shutil.which("google-chrome") or shutil.which("chromium")
pytestmark = pytest.mark.skipif(not CHROME, reason="aucun navigateur Chrome/Chromium trouvé")


@pytest.fixture()
def page(live_server):
    base, _ = live_server
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        context = browser.new_context(accept_downloads=True)
        external = []

        def guard(route):
            url = route.request.url
            if url.startswith(base) or url.startswith("data:"):
                route.continue_()
            else:
                external.append(url)
                route.abort()

        context.route("**/*", guard)
        pg = context.new_page()
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("dialog", lambda d: (pg.errors.append("dialogue inattendu : " + d.message), d.dismiss()))
        pg.base, pg.external = base, external
        pg.goto(base)
        yield pg
        browser.close()


def login(pg, user="admin", pw="motdepasse-admin"):
    pg.fill("#login-user", user)
    pg.fill("#login-pass", pw)
    pg.click("#login-btn")
    pg.wait_for_selector("header.top")


def test_login_errors_then_success_and_logout(page):
    page.fill("#login-user", "admin")
    page.fill("#login-pass", "faux")
    page.click("#login-btn")
    page.wait_for_selector("#toast .error")
    assert "incorrect" in page.inner_text("#toast")
    login(page)
    assert page.is_visible("#estimate-banner")  # mode estimation signalé
    page.click("#logout")
    page.wait_for_selector("#login-btn")
    assert not page.errors


def test_full_user_journey(page):
    login(page)
    page.click("#demo-btn")
    page.wait_for_selector("#parcel-table tbody tr")
    n = page.locator("#parcel-table tbody tr[data-row]").count()
    assert n >= 15
    assert page.locator("#map svg").count() == 1  # repli SVG (pas de Leaflet hors ligne)
    page.click("#optimize-btn")
    page.wait_for_selector("#verification-ok", timeout=60000)
    assert page.locator(".route-card").count() >= 1
    assert page.locator(".kpi").count() == 7
    assert page.locator("[data-alert='DISTANCES_ESTIMEES']").count() == 1
    assert page.locator("#map svg .marker").count() >= n - 3
    # explications chiffrées d'un arrêt
    page.locator(".stop-row").first.click()
    page.wait_for_selector("tr.detail")
    detail = page.inner_text("tr.detail")
    assert "Pourquoi ce livreur" in detail and "Pourquoi cet ordre" in detail and "Pourquoi ce prix" in detail and "Ar" in detail
    # colis écartés et non géolocalisés visibles
    assert page.is_visible("#rejected")
    assert "C0" in page.inner_text("#rejected")
    # export CSV
    with page.expect_download() as dl:
        page.click("#export-csv")
    path = dl.value.path()
    text = open(path, encoding="utf-8-sig").read()
    assert text.startswith("livreur;ordre;adresse") and "ECARTE" in text
    # historique
    page.click("[data-tab=historique]")
    page.wait_for_selector("#history-table")
    page.click(".open-plan")
    page.wait_for_selector(".route-card")
    assert not page.errors and page.external  # des requêtes externes (Leaflet) ont été tentées puis bloquées sans casser l'app


def test_xss_in_address_is_not_executed(page):
    login(page)
    page.click("#add-parcel")
    page.fill("input[aria-label='id_colis ligne 1']", "X1")
    page.fill("input[aria-label='adresse ligne 1']", "<img src=x onerror=\"window.__pwned=1;alert(1)\"><b>gras</b>")
    page.fill("input[aria-label='latitude ligne 1']", "-18.92")
    page.fill("input[aria-label='longitude ligne 1']", "47.53")
    page.click("#optimize-btn")
    page.wait_for_selector(".route-card")
    page.wait_for_timeout(300)
    assert page.evaluate("window.__pwned") is None
    assert page.locator(".route-card img, .route-card b").count() == 0
    assert "<img" in page.inner_text(".route-card")  # affiché comme texte
    assert not page.errors


def test_pick_on_map_sets_coordinates(page):
    login(page)
    page.click("#add-parcel")
    page.click("button.pick")
    page.locator("#map svg").click(position={"x": 300, "y": 200})
    lat = page.input_value("input[aria-label='latitude ligne 1']")
    lon = page.input_value("input[aria-label='longitude ligne 1']")
    assert lat and lon and -19.5 < float(lat) < -18.4 and 47.0 < float(lon) < 48.0


def test_csv_import_and_validation(page, tmp_path):
    login(page)
    good = tmp_path / "ok.csv"
    good.write_text("Colis;Adresse;Lat;Lon\nP1;Rue A;-18.92;47.53\nP2;Rue B;-18.93;47.54\n", encoding="utf-8")
    page.set_input_files("#csv-file", str(good))
    page.wait_for_selector("tr[data-row='1']")
    assert page.input_value("input[aria-label='id_colis ligne 2']") == "P2"
    bad = tmp_path / "bad.csv"
    bad.write_text("foo;bar\n1;2\n", encoding="utf-8")
    page.set_input_files("#csv-file", str(bad))
    page.wait_for_selector("#toast .error")
    assert "Colonnes obligatoires" in page.inner_text("#toast")


def test_optimize_without_parcels_is_refused(page):
    login(page)
    page.click("#optimize-btn")
    page.wait_for_selector("#toast .error")
    assert "au moins un colis" in page.inner_text("#toast")


def test_settings_save_as_admin_and_readonly_for_operator(page):
    login(page)
    page.click("[data-tab=parametres]")
    page.fill("#set-pricing-flat_price_ar", "4500")
    page.click("#save-settings")
    page.wait_for_selector("#toast div:has-text('enregistrés')")
    page.reload()
    page.wait_for_selector("header.top")
    page.click("[data-tab=parametres]")
    assert page.input_value("#set-pricing-flat_price_ar") == "4500"
    page.click("#logout")
    page.wait_for_selector("#login-btn")
    login(page, "oper", "motdepasse-oper")
    page.click("[data-tab=parametres]")
    assert page.is_disabled("#set-pricing-flat_price_ar") and page.locator("#save-settings").count() == 0
    assert not page.errors


def test_account_tab_user_admin(page):
    login(page)
    page.click("[data-tab=compte]")
    page.wait_for_selector("#users-table")
    page.fill("#new-user", "livreur1")
    page.fill("#new-user-pass", "motdepasse-liv")
    page.click("#add-user")
    page.wait_for_selector("#users-table td:text-is('livreur1')")
    page.fill("#old-pass", "faux")
    page.fill("#new-pass", "nouveau-mdp-123")
    page.click("#change-pass")
    page.wait_for_selector("#toast .error")
