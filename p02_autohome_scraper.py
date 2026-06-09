# scraper_engine.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
汽车之家口碑评论爬虫 - 集成版
支持单车型预览与带进度回调的爬取，可直接用于 Flask/Web 系统
"""

import time
import re
import csv
import os
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('autohome_scraper.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class AutohomeReviewScraper:
    def __init__(self, output_dir="outputs"):
        self.driver = None
        self.wait = None
        self.output_dir = output_dir
        self.setup_output_directory()
        self.setup_driver()

    def setup_output_directory(self):
        """创建输出目录"""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            logging.info(f"创建输出目录: {self.output_dir}")

    def setup_driver(self):
        """配置Chrome浏览器 - 使用本地ChromeDriver"""
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.7390.123')

        try:
            import os
            script_dir = os.path.dirname(os.path.abspath(__file__))
            driver_path = os.path.join(script_dir, '..', 'chromedriver-win64', 'chromedriver.exe')
            driver_path = os.path.abspath(driver_path)
            # 备选绝对路径
            driver_path = r'D:\1. 个人研究生论文工作\20. 数据分析整理\chromedriver-win64\chromedriver.exe'
            logging.info(f"尝试使用ChromeDriver路径: {driver_path}")
            if not os.path.exists(driver_path):
                logging.warning(f"ChromeDriver文件不存在: {driver_path}")
                return self.setup_driver_fallback(chrome_options)
            service = Service(executable_path=driver_path)
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.wait = WebDriverWait(self.driver, 10)
            logging.info("浏览器初始化成功（使用本地ChromeDriver）")
            self.driver.get("https://www.baidu.com")
            logging.info(f"浏览器测试成功！标题: {self.driver.title}")
            return True
        except Exception as e:
            logging.error(f"本地ChromeDriver初始化失败: {e}")
            return self.setup_driver_fallback(chrome_options)

    def setup_driver_fallback(self, chrome_options):
        """备选方案：使用WebDriver Manager"""
        try:
            logging.warning("尝试使用WebDriver Manager初始化...")
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.wait = WebDriverWait(self.driver, 10)
            logging.info("浏览器初始化成功（使用WebDriver Manager）")
            self.driver.get("https://www.baidu.com")
            logging.info(f"浏览器测试成功！标题: {self.driver.title}")
            return True
        except Exception as fallback_e:
            logging.error(f"WebDriver Manager初始化也失败: {fallback_e}")
            return False

    # ---------- 原有爬取详情方法 ----------
    def extract_star_rating(self, star_element):
        try:
            star_fill = star_element.find_element(By.CLASS_NAME, "kb-star")
            width_style = star_fill.get_attribute("style")
            width_match = re.search(r'width:\s*(\d+)%', width_style)
            if width_match:
                width_percent = int(width_match.group(1))
                return round(width_percent / 20, 1)
            return 0
        except:
            return 0

    def extract_publish_time(self):
        try:
            timeline_selectors = [
                "div.timeline-con span",
                "div.timeline-con .timeline + span",
                "span:contains('首次发表')",
                ".timeline-con span"
            ]
            for selector in timeline_selectors:
                try:
                    if 'contains' in selector:
                        timeline_elem = self.driver.find_element(By.XPATH, "//span[contains(text(), '首次发表')]")
                    else:
                        timeline_elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    timeline_text = timeline_elem.text.strip()
                    date_patterns = [
                        r'(\d{4}-\d{2}-\d{2})\s+首次发表',
                        r'(\d{4}-\d{1,2}-\d{1,2})\s+首次发表',
                        r'(\d{4}/\d{2}/\d{2})\s+首次发表',
                        r'(\d{4}\.\d{2}\.\d{2})\s+首次发表',
                        r'(\d{4}-\d{2}-\d{2})',
                    ]
                    for pattern in date_patterns:
                        match = re.search(pattern, timeline_text)
                        if match:
                            publish_date = match.group(1)
                            if '/' in publish_date:
                                publish_date = publish_date.replace('/', '-')
                            elif '.' in publish_date:
                                publish_date = publish_date.replace('.', '-')
                            return publish_date
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logging.debug(f"尝试选择器 {selector} 失败: {e}")
                    continue
            try:
                all_spans = self.driver.find_elements(By.TAG_NAME, "span")
                for span in all_spans:
                    text = span.text.strip()
                    if '首次发表' in text or re.match(r'\d{4}-\d{1,2}-\d{1,2}', text):
                        date_match = re.search(r'(\d{4}-\d{1,2}-\d{1,2})', text)
                        if date_match:
                            return date_match.group(1)
            except Exception as e:
                logging.debug(f"遍历span查找时间失败: {e}")
            logging.warning("未找到发表时间")
            return ""
        except Exception as e:
            logging.error(f"提取发表时间失败: {e}")
            return ""

    def extract_review_counts(self):
        try:
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".list_kb_nums__iH75q")))
            total_reviews = 0
            onsale_reviews = 0
            try:
                total_element = WebDriverWait(self.driver, 10).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, ".list_kb_nums__iH75q"))
                )
                total_text = total_element.text
                total_match = re.search(r'(\d+)条口碑', total_text)
                if total_match:
                    total_reviews = int(total_match.group(1))
            except:
                pass
            try:
                onsale_element = WebDriverWait(self.driver, 10).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, ".list_onsale__bWJmL"))
                )
                onsale_text = onsale_element.text
                onsale_match = re.search(r'在售.*?(\d+)篇', onsale_text)
                if onsale_match:
                    onsale_reviews = int(onsale_match.group(1))
            except:
                pass
            return total_reviews, onsale_reviews
        except TimeoutException:
            logging.warning("口碑数量区域加载超时")
            return 0, 0
        except Exception as e:
            logging.error(f"提取口碑数量过程发生异常: {e}")
            return 0, 0

    def extract_car_info(self):
        car_info = {}
        try:
            try:
                car_name = self.driver.find_element(By.CSS_SELECTOR, ".main-series").text
                car_info['车型名称'] = car_name.strip()
            except NoSuchElementException:
                car_info['车型名称'] = ""
            try:
                car_spec = self.driver.find_element(By.CSS_SELECTOR, ".main-spec").text
                car_info['车型版本'] = car_spec.strip()
            except NoSuchElementException:
                car_info['车型版本'] = ""
            car_info['发表时间'] = self.extract_publish_time()

            try:
                user_elem = self.driver.find_element(By.ID, "user_nickname")
                car_info['用户昵称'] = user_elem.text.strip()
            except NoSuchElementException:
                car_info['用户昵称'] = ""

            try:
                title_elem = self.driver.find_element(By.CSS_SELECTOR, "h1.title")
                car_info['口碑标题'] = title_elem.text.strip()
            except NoSuchElementException:
                car_info['口碑标题'] = ""

            info_items = {
                '行驶里程': '', '夏季电耗': '', '春秋电耗': '', '冬季电耗': '',
                '夏季续航': '', '春秋续航': '', '冬季续航': '', '百公里油耗': '',
                '裸车购买价': '', '购买时间': '', '购买地点': ''
            }
            try:
                car_info_sections = self.driver.find_elements(By.CSS_SELECTOR, "ul.car-info")
                for section in car_info_sections:
                    items = section.find_elements(By.CSS_SELECTOR, "li.item-info")
                    for item in items:
                        try:
                            key_elem = item.find_element(By.CSS_SELECTOR, ".key")
                            name_elem = item.find_element(By.CSS_SELECTOR, ".name")
                            key_text = key_elem.text.strip()
                            name_text = name_elem.text.strip()
                            if name_text in info_items:
                                info_items[name_text] = key_text
                        except:
                            continue
            except:
                pass
            car_info.update(info_items)
            return car_info
        except Exception as e:
            logging.error(f"提取车辆信息失败: {e}")
            return car_info

    def extract_interaction_data(self):
        interaction_data = {'观看数': 0, '点赞数': 0, '评论数': 0}
        try:
            WebDriverWait(self.driver, 10).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            time.sleep(1)
            logging.info("尝试触发隐藏的交互数据元素显示...")
            try:
                page_height = self.driver.execute_script("return document.body.scrollHeight")
                scroll_to = page_height // 2
                self.driver.execute_script(f"window.scrollTo(0, {scroll_to});")
                time.sleep(0.5)
                self.driver.execute_script("window.scrollBy(0, 200);")
                time.sleep(0.5)
            except Exception as e:
                logging.warning(f"滚动触发失败: {e}")
            try:
                trigger_selectors = [".kb-item", ".main-content", ".detail-content", ".space.kb-item"]
                from selenium.webdriver.common.action_chains import ActionChains
                for selector in trigger_selectors:
                    try:
                        trigger_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", trigger_element)
                        time.sleep(0.5)
                        ActionChains(self.driver).move_to_element(trigger_element).perform()
                        time.sleep(0.5)
                        break
                    except:
                        continue
            except Exception as e:
                logging.warning(f"悬停触发失败: {e}")
            try:
                hidden_options = self.driver.find_elements(By.CSS_SELECTOR, "div.options.fn-hide")
                for element in hidden_options:
                    self.driver.execute_script("arguments[0].classList.remove('fn-hide');", element)
                time.sleep(0.5)
            except Exception as e:
                logging.warning(f"移除fn-hide类失败: {e}")
            try:
                show_script = """
                var hiddenElements = document.querySelectorAll('div.options.fn-hide');
                hiddenElements.forEach(function(element) {
                    element.classList.remove('fn-hide');
                    element.style.display = 'block';
                    element.style.visibility = 'visible';
                });
                var interactionElements = document.querySelectorAll('.option-views, .option-goods, .option-comments');
                interactionElements.forEach(function(element) {
                    element.style.display = 'inline';
                    element.style.visibility = 'visible';
                });
                return hiddenElements.length;
                """
                self.driver.execute_script(show_script)
                time.sleep(0.5)
            except Exception as e:
                logging.warning(f"JavaScript显示元素失败: {e}")
            try:
                view_elements = self.driver.find_elements(By.CSS_SELECTOR, "span.option-views")
                for elem in view_elements:
                    if elem.is_displayed():
                        text = elem.text.strip()
                        if text.isdigit():
                            interaction_data['观看数'] = int(text)
                            break
                good_elements = self.driver.find_elements(By.CSS_SELECTOR, "span.option-goods")
                for elem in good_elements:
                    if elem.is_displayed():
                        text = elem.text.strip()
                        if text.isdigit():
                            interaction_data['点赞数'] = int(text)
                            break
                comment_elements = self.driver.find_elements(By.CSS_SELECTOR, "span.option-comments")
                for elem in comment_elements:
                    if elem.is_displayed():
                        text = elem.text.strip()
                        if text.isdigit():
                            interaction_data['评论数'] = int(text)
                            break
            except Exception as e:
                logging.error(f"策略1提取失败: {e}")
            if all(value == 0 for value in interaction_data.values()):
                logging.warning("策略1失败，尝试策略2：获取所有匹配元素（包括隐藏的）")
                try:
                    interaction_script = """
                    var result = {views: 0, goods: 0, comments: 0};
                    var viewElements = document.querySelectorAll('span.option-views');
                    for (var i = 0; i < viewElements.length; i++) {
                        var text = viewElements[i].textContent.trim();
                        if (/^\\d+$/.test(text)) { result.views = parseInt(text); break; }
                    }
                    var goodElements = document.querySelectorAll('span.option-goods');
                    for (var i = 0; i < goodElements.length; i++) {
                        var text = goodElements[i].textContent.trim();
                        if (/^\\d+$/.test(text)) { result.goods = parseInt(text); break; }
                    }
                    var commentElements = document.querySelectorAll('span.option-comments');
                    for (var i = 0; i < commentElements.length; i++) {
                        var text = commentElements[i].textContent.trim();
                        if (/^\\d+$/.test(text)) { result.comments = parseInt(text); break; }
                    }
                    return result;
                    """
                    js_result = self.driver.execute_script(interaction_script)
                    if js_result:
                        interaction_data['观看数'] = js_result.get('views', 0)
                        interaction_data['点赞数'] = js_result.get('goods', 0)
                        interaction_data['评论数'] = js_result.get('comments', 0)
                except Exception as e:
                    logging.error(f"策略2失败: {e}")
            if all(value == 0 for value in interaction_data.values()):
                logging.warning("策略2也失败，尝试策略3：查找并处理options容器")
                try:
                    options_containers = self.driver.find_elements(By.CSS_SELECTOR, "div.options")
                    for container in options_containers:
                        self.driver.execute_script("""
                            arguments[0].classList.remove('fn-hide');
                            arguments[0].style.display = 'block';
                            arguments[0].style.visibility = 'visible';
                        """, container)
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", container)
                        time.sleep(0.5)
                        try:
                            view_span = container.find_element(By.CSS_SELECTOR, "span.option-views")
                            if view_span.text.strip().isdigit():
                                interaction_data['观看数'] = int(view_span.text.strip())
                        except:
                            pass
                        try:
                            good_span = container.find_element(By.CSS_SELECTOR, "span.option-goods")
                            if good_span.text.strip().isdigit():
                                interaction_data['点赞数'] = int(good_span.text.strip())
                        except:
                            pass
                        try:
                            comment_span = container.find_element(By.CSS_SELECTOR, "span.option-comments")
                            if comment_span.text.strip().isdigit():
                                interaction_data['评论数'] = int(comment_span.text.strip())
                        except:
                            pass
                        if any(value > 0 for value in interaction_data.values()):
                            break
                except Exception as e:
                    logging.error(f"策略3失败: {e}")
            return interaction_data
        except Exception as e:
            logging.error(f"提取交互数据失败: {e}")
            return interaction_data

    def extract_review_details(self):
        review_data = {}
        try:
            review_data['最满意'] = ""
            satisfied_selectors = [
                "//h1[contains(text(), '最满意')]/following-sibling::p[@class='kb-item-msg']",
                "//h1[text()='最满意']/following-sibling::p[@class='kb-item-msg']",
                "//div[@class='space kb-item']//h1[contains(text(), '最满意')]/following-sibling::p",
                "//div[contains(@class, 'kb-item')]//h1[contains(text(), '最满意')]/../p[@class='kb-item-msg']"
            ]
            for selector in satisfied_selectors:
                try:
                    satisfied_elem = self.driver.find_element(By.XPATH, selector)
                    review_data['最满意'] = satisfied_elem.text.strip()
                    break
                except:
                    continue
            review_data['最不满意'] = ""
            unsatisfied_selectors = [
                "//h1[contains(text(), '最不满意')]/following-sibling::p[@class='kb-item-msg']",
                "//h1[text()='最不满意']/following-sibling::p[@class='kb-item-msg']",
                "//div[@class='space kb-item']//h1[contains(text(), '最不满意')]/following-sibling::p",
                "//div[contains(@class, 'kb-item')]//h1[contains(text(), '最不满意')]/../p[@class='kb-item-msg']"
            ]
            for selector in unsatisfied_selectors:
                try:
                    unsatisfied_elem = self.driver.find_element(By.XPATH, selector)
                    review_data['最不满意'] = unsatisfied_elem.text.strip()
                    break
                except:
                    continue
            categories = ['空间', '驾驶感受', '续航', '外观', '内饰', '性价比', '智能化', '油耗', '配置']
            for category in categories:
                try:
                    category_selectors = [
                        f"//h1[contains(text(), '{category}')]",
                        f"//div[@class='space kb-item']//h1[contains(text(), '{category}')]"
                    ]
                    category_elem = None
                    for selector in category_selectors:
                        try:
                            category_elem = self.driver.find_element(By.XPATH, selector)
                            break
                        except:
                            continue
                    if category_elem:
                        try:
                            star_container = category_elem.find_element(By.CSS_SELECTOR, ".athm-star")
                            rating = self.extract_star_rating(star_container)
                            review_data[f'{category}评分'] = rating
                        except:
                            review_data[f'{category}评分'] = 0
                        comment_selectors = [
                            "./following-sibling::p[@class='kb-item-msg']",
                            "../p[@class='kb-item-msg']",
                            "./parent::div/p[@class='kb-item-msg']"
                        ]
                        comment_text = ""
                        for comment_selector in comment_selectors:
                            try:
                                comment_elem = category_elem.find_element(By.XPATH, comment_selector)
                                comment_text = comment_elem.text.strip()
                                break
                            except:
                                continue
                        review_data[f'{category}评论'] = comment_text
                    else:
                        review_data[f'{category}评分'] = 0
                        review_data[f'{category}评论'] = ""
                except Exception as e:
                    logging.error(f"提取{category}信息失败: {e}")
                    review_data[f'{category}评分'] = 0
                    review_data[f'{category}评论'] = ""
            return review_data
        except Exception as e:
            logging.error(f"提取评论详情失败: {e}")
            return review_data

    def scrape_review_page(self, review_url):
        try:
            self.driver.get(review_url)
            time.sleep(1)
            try:
                self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "kb-item")))
            except TimeoutException:
                try:
                    self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".main-series")))
                except TimeoutException:
                    logging.error(f"页面加载超时: {review_url}")
                    return None
            car_info = self.extract_car_info()
            review_details = self.extract_review_details()
            interaction_data = self.extract_interaction_data()
            result = {**car_info, **review_details, **interaction_data}
            result['评论链接'] = review_url
            result['爬取时间'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return result
        except Exception as e:
            logging.error(f"爬取评论页面失败 {review_url}: {e}")
            return None

    def extract_purchase_purposes(self, review_elements):
        purchase_purposes = []
        try:
            purpose_divs = self.driver.find_elements(By.CSS_SELECTOR, "div.list_buy_target__rsfaE")
            for purpose_div in purpose_divs:
                try:
                    purpose_list = purpose_div.find_elements(By.CSS_SELECTOR, "li.list_target__76fWs")
                    purposes = [li.text.strip() for li in purpose_list if li.text.strip()]
                    purchase_purposes.append(", ".join(purposes))
                except Exception as e:
                    logging.warning(f"提取单个购车目的失败: {e}")
                    purchase_purposes.append("")
        except Exception as e:
            logging.error(f"提取购车目的失败: {e}")
        while len(purchase_purposes) < len(review_elements):
            purchase_purposes.append("")
        if len(purchase_purposes) > len(review_elements):
            purchase_purposes = purchase_purposes[:len(review_elements)]
        logging.info(f"提取到{len(purchase_purposes)}个购车目的")
        return purchase_purposes

    def get_review_links_with_purposes(self, car_id, max_pages=100):
        review_data_list = []
        base_url = f"https://k.autohome.com.cn/{car_id}?order=1"
        try:
            self.driver.get(base_url)
            time.sleep(0.5)
            total_reviews, onsale_reviews = self.extract_review_counts()
            logging.info(f"车型{car_id}口碑统计: 总口碑={total_reviews} 在售口碑={onsale_reviews}")
            for page in range(1, max_pages + 1):
                logging.info(f"正在爬取车型{car_id}第{page}页")
                try:
                    self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".list_nice_value__hI2Bw")))
                    detail_links = self.driver.find_elements(By.XPATH, "//a[contains(text(), '查看完整口碑')]")
                    purchase_purposes = self.extract_purchase_purposes(detail_links)
                    for i, link in enumerate(detail_links):
                        href = link.get_attribute('href')
                        if href:
                            purpose = purchase_purposes[i] if i < len(purchase_purposes) else ""
                            review_data_list.append({
                                'link': href,
                                'purchase_purpose': purpose,
                                '总口碑数量': total_reviews,
                                '在售口碑数量': onsale_reviews
                            })
                    if page < max_pages:
                        try:
                            next_selectors = [
                                "//a[contains(@class, 'athm-page-next')]",
                                "//a[@class='ace-pagination__btn next']",
                                "//a[contains(text(), '下一页')]"
                            ]
                            next_clicked = False
                            for selector in next_selectors:
                                try:
                                    next_button = self.driver.find_element(By.XPATH, selector)
                                    if 'disabled' not in next_button.get_attribute('class'):
                                        next_button.click()
                                        time.sleep(0.5)
                                        next_clicked = True
                                        break
                                except:
                                    continue
                            if not next_clicked:
                                logging.info("已到达最后一页")
                                break
                        except:
                            logging.info("找不到下一页按钮，可能已到最后一页")
                            break
                except TimeoutException:
                    logging.error(f"页面{page}加载超时")
                    break
                except Exception as e:
                    logging.error(f"爬取第{page}页时出错: {e}")
                    continue
            logging.info(f"车型{car_id}共找到{len(review_data_list)}个评论链接")
            return review_data_list
        except Exception as e:
            logging.error(f"获取评论链接失败: {e}")
            return review_data_list

    # ---------- 新增加的方法 ----------
    def get_car_preview(self, car_id):
        """
        访问口碑列表首页，提取车系名称和口碑数量
        返回 dict 或 None
        """
        base_url = f"https://k.autohome.com.cn/{car_id}?order=1"
        try:
            self.driver.get(base_url)
            time.sleep(1)
            # 提取车系名称（从页面标题或特定元素）
            car_name = ""
            try:
                title = self.driver.title.replace("_口碑_汽车之家", "").strip()
                if title:
                    car_name = title
            except:
                pass
            if not car_name:
                try:
                    car_name = self.driver.find_element(By.CSS_SELECTOR, ".title-series").text.strip()
                except:
                    car_name = "未知车型"

            total_reviews, onsale_reviews = self.extract_review_counts()
            return {
                "car_id": car_id,
                "car_name": car_name,
                "total_reviews": total_reviews,
                "in_sale_reviews": onsale_reviews
            }
        except Exception as e:
            logging.error(f"获取车型预览失败: {e}")
            return None

    def scrape_with_progress(self, car_id, car_name, progress_callback):
        """
        爬取单车型，通过 progress_callback(percent, message) 更新进度
        返回最终 CSV 文件路径，失败返回 None
        """
        progress_callback(0, "开始获取口碑链接...")
        review_links_data = self.get_review_links_with_purposes(car_id)
        total = len(review_links_data)
        if total == 0:
            progress_callback(100, "未找到任何口碑")
            return None

        all_reviews = []
        for i, item in enumerate(review_links_data, 1):
            percent = int(i / total * 90)
            progress_callback(percent, f"爬取评论 {i}/{total}")
            detail = self.scrape_review_page(item['link'])
            if detail:
                detail.update({
                    '购车目的': item['purchase_purpose'],
                    '总口碑数量': item.get('总口碑数量', 0),
                    '在售口碑数量': item.get('在售口碑数量', 0)
                })
                all_reviews.append(detail)
            time.sleep(0.3)

        # 保存为 CSV
        filename = f"{car_name}_{car_id}.csv"
        success = self.save_to_csv(all_reviews, filename)
        if success:
            filepath = os.path.join(self.output_dir, filename)
            progress_callback(100, f"爬取完成，共 {len(all_reviews)} 条评论，文件: {filename}")
            return filepath
        else:
            progress_callback(100, "保存文件失败")
            return None

    def save_to_csv(self, data, filename):
        try:
            if not data:
                logging.warning("没有数据可保存")
                return False
            fieldnames = [
                '总口碑数量', '在售口碑数量',
                '车型名称', '车型版本', '发表时间', '用户昵称', '口碑标题',
                '行驶里程', '夏季电耗', '春秋电耗', '冬季电耗',
                '夏季续航', '春秋续航', '冬季续航', '百公里油耗', '裸车购买价',
                '购买时间', '购买地点', '最满意', '最不满意',
                '空间评分', '空间评论', '驾驶感受评分', '驾驶感受评论',
                '续航评分', '续航评论', '外观评分', '外观评论',
                '内饰评分', '内饰评论', '性价比评分', '性价比评论',
                '智能化评分', '智能化评论', '油耗评分', '油耗评论',
                '配置评分', '配置评论', '观看数', '点赞数', '评论数',
                '购车目的', '评论链接', '爬取时间'
            ]
            filepath = os.path.join(self.output_dir, filename)
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for row in data:
                    writer.writerow(row)
            logging.info(f"数据已保存到 {filepath}")
            return True
        except Exception as e:
            logging.error(f"保存CSV文件失败: {e}")
            return False

    def close(self):
        if self.driver:
            self.driver.quit()
            self.driver = None

# 本地调试入口
if __name__ == "__main__":
    scraper = AutohomeReviewScraper(output_dir="outputs")
    try:
        # 测试预览
        preview = scraper.get_car_preview("8171")
        print("预览:", preview)
        # 测试带进度爬取（需较长时间，此处仅示意）
        if preview:
            def my_progress(pct, msg):
                print(f"[{pct}%] {msg}")
            filepath = scraper.scrape_with_progress("8171", preview['car_name'], my_progress)
            print("最终文件:", filepath)
    finally:
        scraper.close()