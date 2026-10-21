# -*- coding: utf-8 -*-
from ..client import ShopeeModifyClient


def delete_category(client: ShopeeModifyClient, store_id: str, catalog_id: int | str) -> bool:
    """
    Menghapus kategori (catalog) dari toko di Shopee.
    Endpoint: DELETE https://foody.shopee.co.id/api/seller/store/catalogs/{catalog_id}
    """
    url = f"https://foody.shopee.co.id/api/seller/store/catalogs/{str(catalog_id)}"
    try:
        resp = client.session.delete(
            url,
            headers=client._seller_headers(override_entity_id=store_id),
            timeout=15
        )
        data = resp.json()
        if data.get("code") == 0:
            return True
        client.last_error = f"API error: code={data.get('code')} msg={data.get('msg')}"
    except Exception as e:
        client.last_error = str(e)
    return False


def delete_dish(client: ShopeeModifyClient, store_id: str, dish_id: int | str) -> bool:
    """
    Menghapus menu (dish) dari toko di Shopee.
    Endpoint: DELETE https://foody.shopee.co.id/api/seller/store/dishes/{dish_id}
    """
    url = f"https://foody.shopee.co.id/api/seller/store/dishes/{str(dish_id)}"
    try:
        resp = client.session.delete(
            url,
            headers=client._seller_headers(override_entity_id=store_id),
            timeout=15
        )
        data = resp.json()
        if data.get("code") == 0:
            return True
        client.last_error = f"API error: code={data.get('code')} msg={data.get('msg')}"
    except Exception as e:
        client.last_error = str(e)
    return False
