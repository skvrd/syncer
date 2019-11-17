from dataclasses import dataclass
from typing import List
from decimal import Decimal
from ebaysdk.trading import Connection as Trading
import datetime

import yaml


@dataclass
class InventoryItem:
    sku: str
    price: Decimal


@dataclass
class EbayInventoryItem(InventoryItem):
    id: str


@dataclass
class Shop:
    name: str
    type: str
    config: dict
    master: bool = False

    def _get_ebay_items(self) -> List[EbayInventoryItem]:
        result = []
        api = Trading(config_file=None, **self.config)
        page_number = 0
        max_page_number = 1
        while page_number < max_page_number:
            page_number += 1
            page = api.execute('GetSellerList',  {
                'StartTimeFrom':
                    (datetime.datetime.now() - datetime.timedelta(days=31))
                    .strftime("%Y-%m-%dT%H:%M:%S"),
                'StartTimeTo':
                    datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                'GranularityLevel': 'Fine',
                'Pagination': {
                    'EntriesPerPage':
                        100,
                    "PageNumber": page_number}
            }).dict()
            items = page.get('ItemArray').get("Item")
            if type(items) != list:
                items = [items]
            for item in items:
                result.append(
                    EbayInventoryItem(
                        item['SKU'],
                        Decimal(
                            item['ListingDetails']
                                ['ConvertedStartPrice']['value']
                        ),
                        item['ItemID']
                    )
                )
        return result

    def get_items(self) -> List[InventoryItem]:
        if self.type == 'ebay':
            return self._get_ebay_items()
        raise NotImplementedError(f"Unsupported type '{self.type}'s")


config = yaml.safe_load(open('config.yml', 'r'))
shops = [Shop(**shop) for shop in config.get("shops")]

master = dict()
synced = dict()
for shop in shops:
    if shop.master:
        for item in shop.get_items():
            if master.get(item.sku):
                master[item.sku].append(item)
            else:
                master[item.sku] = [item]
    else:
        for item in shop.get_items():
            if synced.get(item.sku):
                synced[item.sku].append(item)
            else:
                synced[item.sku] = [item]