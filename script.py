import datetime
import requests
import time
import yaml
import schedule
import sentry_sdk

from dataclasses import dataclass
from decimal import Decimal, getcontext
from ebaysdk.trading import Connection as Trading


@dataclass
class Shop:
    name: str
    type: str
    config: dict
    master: bool = False
    coefficient: float = 1

    def _get_ebay_items(self):
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
                        self,
                        item['ItemID'],
                    )
                )
            max_page_number = int(page.get('PaginationResult')
                                  .get('TotalNumberOfPages'))
        return result

    def _get_shopify_items(self):
        end_point_url = \
            f"https://{self.name}.myshopify.com/admin/api/graphql.json"
        headers = {
            "X-Shopify-Access-Token": self.config["password"],
            "X-GraphQL-Cost-Include-Fields": "true",
            "Content-Type": "application/graphql"
        }
        cursor = ''
        hasNextPage = True
        results = []

        while hasNextPage:
            hasNextPage = False
            payload = '''
            {
                productVariants(first:250%s) {
                    edges {
                        cursor
                        node {
                            id
                            sku
                            price
                            displayName
                        }
                    }
                    pageInfo {
                        hasNextPage
                    }
                }
            }
            ''' % cursor
            response = requests.post(
                end_point_url,
                data=payload,
                headers=headers,
            )
            result = response.json()
            if 'data' not in result:
                print(result)
            for item in result['data']['productVariants']['edges']:
                cursor = f',after:"{item["cursor"]}"'
                results.append(
                    ShopifyInventoryItem(
                        item['node']['sku'],
                        Decimal(item['node']['price']),
                        self,
                        item['node']['id'],
                    )
                )
            hasNextPage = bool(result['data']['productVariants'][
                               'pageInfo']['hasNextPage'])
            throttle_status = str(result['extensions']['cost']
                                  ['throttleStatus']['currentlyAvailable'])
            if int(throttle_status) < 300:
                print("sleeping for 10 seconds...", len(results))
                time.sleep(10)
        return results

    def get_items(self):
        if self.type == 'ebay':
            return self._get_ebay_items()
        elif self.type == 'shopify':
            return self._get_shopify_items()
        raise NotImplementedError(f"Unsupported type '{self.type}'s")


@dataclass
class InventoryItem:
    sku: str
    price: Decimal
    shop: Shop


@dataclass
class ShopifyInventoryItem(InventoryItem):
    id: str

    def save(self):
        end_point_url = \
            f"https://{self.shop.name}.myshopify.com/admin/api/graphql.json"
        headers = {
            "X-Shopify-Access-Token": self.shop.config["password"],
            "X-GraphQL-Cost-Include-Fields": "true",
            "Content-Type": "application/graphql"
        }
        payload = f'''
            mutation {{
                productVariantUpdate(input: {{id: "{self.id}", price: "{self.price}" }}) {{
                    productVariant {{
                        id
                    }}
                }}
            }}
        '''
        response = requests.post(
            end_point_url,
            data=payload,
            headers=headers,
        )
        response.raise_for_status()


@dataclass
class EbayInventoryItem(InventoryItem):
    id: str


# TODO: Unit test this function
def list_to_dict_by_sku(array, result=None):
    if not result:
        result = {}
    for item in array:
        if result.get(item.sku):
            result[item.sku].append(item)
        else:
            result[item.sku] = [item]
    return result


def work(config):

    shops = [Shop(**shop) for shop in config.get("shops")]

    master = dict()
    synced = dict()
    for shop in shops:
        if shop.master:
            master = list_to_dict_by_sku(shop.get_items())
        else:
            synced = list_to_dict_by_sku(shop.get_items(), synced)

    for sku, master_item in master.items():
        for item in synced.get(sku, []):
            if abs(float(master_item[0].price) * item.shop.coefficient -
                   float(item.price)) > 0.1:
                print(f"(SKU: {sku}) Update {item.id} to "
                      f"{float(master_item[0].price) * item.shop.coefficient} "
                      f"from {item.price}")
                item.price = \
                    Decimal(float(master_item[0].price)
                            * item.shop.coefficient)
                item.save()


config = yaml.safe_load(open('config.yml', 'r'))

if config.get("sentry"):
    sentry_sdk.init(config.get("sentry"))
    x = 1/0

getcontext().prec = 2
schedule.every().hour.do(work, config=config)
while True:
    schedule.run_pending()
    time.sleep(1)
