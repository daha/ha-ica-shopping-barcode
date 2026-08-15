"""Constants for the ICA API client (no Home Assistant imports)."""

from __future__ import annotations

IMS_BASE = "https://ims.icagruppen.se"
API_BASE = "https://apimgw-pub.ica.se"

TOKEN_ENDPOINT = f"{IMS_BASE}/oauth/v2/token"
AUTHORIZE_ENDPOINT = f"{IMS_BASE}/oauth/v2/authorize"
REGISTER_ENDPOINT = f"{IMS_BASE}/register"
LOGIN_ENDPOINT = f"{IMS_BASE}/authn/authenticate/IcaCustomers"

DCR_CLIENT_ID = "ica-app-dcr-registration"
DCR_CLIENT_SECRET = "uxLHTBvZ-Z2fV-SbrHl1E-tz7vB3jQFrwAdSLlbVMMu1rxDdvJU0s8KGu9d1wLS4"
DCR_SOFTWARE_ID = "dcr-ica-app-template"

REDIRECT_URI = "icacurity://app"
ACR = "urn:se:curity:authentication:html-form:IcaCustomers"

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15"
)

# Web shopping-list service (ica.se) — the API our account actually uses.
#   list all:   GET    {SHOPPING_LIST_BASE}/list/all
#   add row:    POST   {SHOPPING_LIST_BASE}/list/{list_id}/row
#   update row: PUT    {SHOPPING_LIST_BASE}/row/{row_id}  (Phase 2: check; full row)
#   delete row: DELETE {SHOPPING_LIST_BASE}/row/{row_id}  (Phase 2: no body)
SHOPPING_LIST_BASE = f"{API_BASE}/sverige/digx/shopping-list/v1/api"
# Product service (EAN/GTIN lookup) — GET {PRODUCT_URL}/{ean}.
# Returns name + articleId + articleGroupId + expandedArticleGroupId, i.e.
# everything needed to categorise the row; no separate article-search is needed.
PRODUCT_URL = f"{API_BASE}/sverige/digx/mobile/productservice/v1/product"
# Article-group reference table, for resolving a product's category to clear text.
# Returns {"articleGroups": [{"id", "name", "parentId", "lastSyncDate"}, ...]} —
# 10 COARSE groups only (expanded group ids are not in this table). Static data
# (rows stamped 2015), so it is fetched once per session and cached.
ARTICLE_GROUPS_URL = (
    f"{API_BASE}/sverige/digx/mobile/shoppinglistservice/v1"
    "/articles/articlegroups?lastsyncdate=2001-01-01"
)
