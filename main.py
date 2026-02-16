import os
import sys
#  import PyPDF
from pypdf import PdfReader, PdfWriter
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from PDFRepair import *

# Настройка Google Sheets и Google Drive
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'C:/Users/Admin/OneDrive/Документы/pdfassistantforapplicants-5c2af679fac9.json'  # Путь к вашему JSON файлу сервисного аккаунта

credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
sheets_service = build('sheets', 'v4', credentials=credentials)
drive_service = build('drive', 'v3', credentials=credentials)

# ID Google Sheets документов и папок на Google Drive
CLIENTS_SPREADSHEET_ID = '1GcE51R3_L07o5w0deD7Axk32EWJVMnOhwZmNXmWCjIg'
MAPPING_SPREADSHEET_ID = '19MfKvlPe6P7slOlYVi0frrpgx53jHh_cCShfH49WlaA'
PDF_TEMPLATES_FOLDER_ID = '1gtDHd8tDwYpNqikGoKixufJtLvuTfKyZ'
FILLED_PDF_FOLDER_ID = '1hV2nO47XHAB1RKfwsVctkOj_2OEOuAb3'

# выводить отладку
DEBUG_INFO = True
# проверять корректность данных
VALIDATION_ON = False

# Функция для получения данных анкеты заявителя из отдельной вкладки
def get_applicant_data(surname):
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=CLIENTS_SPREADSHEET_ID,
            range=f"'{surname}'!A:B",  # Используем вкладку по фамилии заявителя
            valueRenderOption='UNFORMATTED_VALUE'  # Получаем значения как есть
        ).execute()
        
        values = result.get('values', [])
        data_dict = {}
        
        for row in values:
            if len(row) == 2:
                field_name = row[1]   # Название поля в колонке B
                field_value = row[0]  # Значение поля в колонке A
                data_dict[field_name] = field_value
                
        return data_dict
    except Exception as e:
        print(f"Ошибка при получении данных для {surname}: {e}")
        return None

# Функция для получения маппинга полей из файла Mapping
def get_mapping():
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=MAPPING_SPREADSHEET_ID,
            range='Map!A:Z'  # Используем правильное название листа
        ).execute()
        
        values = result.get('values', [])
        if not values:
            return {}
            
        # Первая строка - названия шаблонов (начиная с колонки B)
        template_names = []
        if len(values[0]) > 1:
            template_names = [cell.strip() for cell in values[0][1:]]
            
        mapping = {template: {} for template in template_names}

        if DEBUG_INFO:
            print("Шаблоны в файле Mapping:")
            for i, name in enumerate(template_names, start=1):
                print(f"{i}. {name}")
        
        # Остальные строки - соответствия полей
        for row in values[1:]:
            if len(row) > 0:
                sheet_field = row[0].strip()  # Название поля из анкеты Google Sheets
                
                # Проверка на специальную строку #DAY
                if sheet_field == "#DAY":
                    continue  # Обработка будет при заполнении форм
                    
                # Соответствия для каждого шаблона
                for i, template in enumerate(template_names):
                    if len(row) > i + 1 and row[i + 1].strip():
                        pdf_field = row[i + 1].strip()
                        mapping[template][sheet_field] = pdf_field
                        # if DEBUG_INFO:  print(f"{template}.{sheet_field}=>{pdf_field}")
                        
        return mapping
    except Exception as e:
        print(f"Ошибка при получении маппинга: {e}")
        return None

# Функция для получения списка файлов в папке Google Drive
def list_files_in_folder(folder_id):
    try:
        results = drive_service.files().list(
            q=f"'{folder_id}' in parents and mimeType='application/pdf'",
            fields="files(id, name)"
        ).execute()
        
        items = results.get('files', [])
        return items
    except Exception as e:
        print(f"Ошибка при получении файлов из папки: {e}")
        return []

def check_folder_exists_by_name(folder_name, parent_folder_id=None):
    """
    Проверяет, существует ли папка с заданным именем в Google Drive.

    Args:
        folder_name (str): Имя папки для поиска.
        parent_folder_id (str, optional): ID родительской папки для поиска.
                                          Если None, поиск идет по всему диску.

    Returns:
        
               - Второй элемент: словарь с данными первой найденной папки
                                 (если папка найдена) или None.
    """
    # Формируем поисковый запрос: имя + тип "папка" + не в корзине
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    
    # Если указана родительская папка, добавляем условие
    if parent_folder_id:
        query += f" and '{parent_folder_id}' in parents"
    
    try:
        # Выполняем поиск
        results = drive_service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name, mimeType, webViewLink)',
            pageSize=10
        ).execute()
        
        folders = results.get('files', [])
        
        if folders:
            # Папка найдена (берем первую, если есть несколько с одинаковым именем)
            return folders[0].get('id')
        else:
            # Папка не найдена
            return None
            
    except Exception as error:
        print(f"Произошла ошибка при обращении к Drive API: {error}")
        return None

# Функция для создания подпапки для заявителя в Google Drive
def create_applicant_folder(folder_name, parent_folder_id):
    try:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }
        
        folder_id = check_folder_exists_by_name(folder_name, parent_folder_id)
        if folder_id == None:
            if DEBUG_INFO: print (f"Папка не существует. Создаем")
            folder = drive_service.files().create(body=file_metadata, fields='id').execute()
            folder_id = folder.get('id')
        return folder_id
    except Exception as e:
        print(f"Ошибка при создании папки для {folder_name}: {e}")
        return None

# Функция для скачивания файла с Google Drive
def download_file(file_id, destination):
    try:
        request = drive_service.files().get_media(fileId=file_id)
        with open(destination, 'wb') as f:
            # Используем MediaIoBaseDownload для потокового скачивания
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
        return True
    except Exception as e:
        print(f"Ошибка при скачивании файла: {e}")
        return False

# Функция для загрузки PDF в Google Drive
def upload_pdf_to_drive(file_path, folder_id, file_name):
    try:
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        media = MediaFileUpload(file_path, mimetype='application/pdf')
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        print(f"Ошибка при загрузке файла: {e}")
        return None

# Функция для заполнения PDF формы
def fill_pdf_form(template_path, output_path, data_dict, mapping, template_name):
    try:
        with open(template_path, 'rb') as template_file:
            pdf_reader = PdfReader(template_file)
            pdf_writer = PdfWriter(clone_from=pdf_reader)

            print (f"Open and clone")

            # Копируем страницы из оригинала
            #for page_num in range(len(pdf_reader.pages)):
            #    page = pdf_reader.pages[page_num]
            #    pdf_writer.add_page(page)
            #pdf_writer.append(pdf_reader)

            #print (f"Copy")

            # Получаем соответствие полей для данного шаблона
            template_mapping = mapping.get(template_name, {})

            fields = pdf_writer.get_fields()
            if not fields  == None:
                print(f"Найдено полей: {len(fields)}")
                print("Список полей и их текущие значения (если доступны):")
                for field_name, field_object in fields.items():
                     # Объект поля может содержать различные атрибуты, например /V (значение)
                     # Подробнее о структуре поля: https://gitlab.elegosoft.com/elego/PyPDF2/-/blame/219bb09021a1d607803f27eb195354f75dda29fd/PyPDF2/pdf.py [citation:2]
                    field_value = field_object.get('/V', 'не заполнено')
                    print(f"  - Имя: '{field_name}', Текущее значение: {field_value}")
            else:
                print("Не удалось получить список полей. ")
                # restore_acroform_from_annotations(template_file, 'PDF_Restored.pdf')
                # sys.exit()

            # Проходим по всем аннотациям (полям формы) в каждой странице
            for j in range(len(pdf_writer.pages)):
                page = pdf_writer.pages[j]
                #  print (f"page {page}")

                if '/Annots' in page:
                    for annot in page['/Annots']:
                        if '/T' in annot:
                            pdf_field_name = annot['/T']

                            print (f"pdf_field_name = {pdf_field_name}")
                            
                            # Ищем, какое поле из анкеты соответствует этому полю PDF
                            sheet_field_name = None
                            for sf, pf in template_mapping.items():
                                if pf == pdf_field_name:
                                    sheet_field_name = sf
                                    break
                                    
                            if sheet_field_name and sheet_field_name in data_dict:
                                field_value = data_dict[sheet_field_name]
                                
                                # Проверка на необходимость извлечения дня из даты
                                if "#DAY" in template_mapping and template_mapping["#DAY"] == pdf_field_name:
                                    try:
                                        # Пытаемся распарсить дату и извлечь день
                                        date_obj = datetime.strptime(field_value, '%Y-%m-%d')
                                        field_value = str(date_obj.day)
                                    except ValueError:
                                        # Если не получается, оставляем как есть
                                        pass
                                        
                                # Устанавливаем значение поля
                                """ annot.update({
                                    PdfWriter..generic.NameObject('/V'): PyPDF.generic.TextStringObject(field_value)
                                }) """

        with open(output_path, 'wb') as output_file:
            pdf_writer.write(output_file)
            
        return True
    except Exception as e:
        print(f"Ошибка при заполнении PDF формы: {e}")
        return False

class FormValidator:
    """
    Класс для валидации данных анкет перед заполнением PDF форм
    """
    def __init__(self):
        # Словарь с допустимыми значениями для различных полей
        self.valid_values = {
            'gender': ['муж', 'жен', 'male', 'female', 'м', 'ж'],
            'marital_status': ['холост', 'замужем', 'женат', 'разведен', 'вдовец', 'вдова',
                             'single', 'married', 'divorced', 'widower', 'widow'],
            'nationality': ['российская', 'русская', 'russian', 'испанская', 'spanish',
                          'украинская', 'украинец', 'украинка', 'ukrainian']
        }
        
    def is_russian_text(self, text):
        """
        Проверяет, содержит ли текст русские буквы
        """
        if not text:
            return False
            
        russian_chars = set('абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ')
        return any(char in russian_chars for char in str(text))
    
    def validate_field(self, field_name, field_value, field_type=None):
        """
        Валидирует отдельное поле
        """
        if not field_value:
            return True, "Поле пустое - пропускаем валидацию"
            
        field_name_lower = field_name.lower()
        
        # Проверка на русский текст в полях, где он не допустим
        if any(keyword in field_name_lower for keyword in ['code', 'number', 'номер', 'код', 'id', 'identifier']):
            if self.is_russian_text(field_value):
                return False, f"Поле '{field_name}' содержит русский текст, но должно содержать только цифры или латинские буквы"
                
        # Проверка пола
        if any(keyword in field_name_lower for keyword in ['пол', 'gender', 'sex']):
            if field_value.lower() not in self.valid_values['gender']:
                return False, f"Некорректное значение поля '{field_name}': '{field_value}'. Допустимые значения: {', '.join(self.valid_values['gender'])}"
                
        # Проверка семейного положения
        if any(keyword in field_name_lower for keyword in ['семейное положение', 'marital', 'статус', 'status']):
            if field_value.lower() not in self.valid_values['marital_status']:
                return False, f"Некорректное значение поля '{field_name}': '{field_value}'. Допустимые значения: {', '.join(self.valid_values['marital_status'])}"
                
        # Проверка гражданства
        if any(keyword in field_name_lower for keyword in ['гражданство', 'национальность', 'citizenship', 'nationality']):
            if field_value.lower() not in self.valid_values['nationality']:
                return False, f"Некорректное значение поля '{field_name}': '{field_value}'. Допустимые значения: {', '.join(self.valid_values['nationality'])}"
                
        return True, "Поле валидно"
    
    def validate_applicant_data(self, data_dict, required_fields=None):
        """
        Валидирует все данные заявителя
        """
        if required_fields is None:
            required_fields = []
            
        errors = []
        warnings = []
        
        # Проверка обязательных полей
        for field in required_fields:
            if field not in data_dict or not data_dict[field]:
                errors.append(f"Отсутствует обязательное поле: {field}")
                
        # Валидация каждого поля
        for field_name, field_value in data_dict.items():
            is_valid, message = self.validate_field(field_name, field_value)
            if not is_valid:
                errors.append(message)
            elif "Поле пустое" not in message:
                warnings.append(f"{field_name}: {message}")
                
        return len(errors) == 0, errors, warnings

# Основная логика программы
if __name__ == '__main__':
    # Получение маппинга полей
    mapping = get_mapping()
    if not mapping:
        print("Не удалось получить маппинг полей. Завершение работы.")
        exit()
        
    print(f"Получено маппингов для шаблонов: {list(mapping.keys())}")
    
    # Получение списка шаблонов PDF из папки на Google Drive
    template_files = list_files_in_folder(PDF_TEMPLATES_FOLDER_ID)
    if not template_files:
        print("Не найдено шаблонов PDF. Завершение работы.")
        exit()
    else:
        # print(f"Найдено шаблонов PDF: {list(template_files('name'))}")
        pass
        
    # Создаем временные папки
    os.makedirs('templates', exist_ok=True)
    os.makedirs('filled_forms', exist_ok=True)
    
    # Скачиваем шаблоны
    template_paths = {}
    for file in template_files:
        template_name = file['name']
        if template_name.endswith('.pdf'):
            local_path = os.path.join('templates', template_name)
            if download_file(file['id'], local_path):
                template_paths[template_name] = local_path
                
    if not template_paths:
        print("Не удалось скачать ни одного шаблона. Завершение работы.")
        exit()
        
    # Получение списка вкладок из файла Clients_for_PDF (предполагается, что есть способ получить список листов)
    try:
        spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=CLIENTS_SPREADSHEET_ID, includeGridData=False).execute()
        sheets = spreadsheet.get('sheets', [])
        
        # Создаем валидатор
        validator = FormValidator()
        
        for sheet in sheets:
            surname = sheet['properties']['title']
            print(f"Обработка заявителя: {surname}")
            
            # Получение данных анкеты
            applicant_data = get_applicant_data(surname)
            if not applicant_data:
                print(f"Пропуск заявителя {surname} из-за ошибки при получении данных.")
                continue
                
            if VALIDATION_ON:
                # Валидация данных анкеты
                is_valid, errors, warnings = validator.validate_applicant_data(
                    applicant_data,
                    required_fields=['Фамилия', 'Имя', 'Дата рождения', 'Пол']  # Пример обязательных полей
                )
                
                if not is_valid:
                    print(f"Ошибки валидации для {surname}:")
                    for error in errors:
                        print(f"  - {error}")
                    continue  # Пропускаем заявителя с ошибками
                
                if warnings:
                    print(f"Предупреждения для {surname}:")
                    for warning in warnings:
                        print(f"  - {warning}")
            
            # Создание папки для заявителя в FilledPDF
            applicant_folder_id = create_applicant_folder(surname, FILLED_PDF_FOLDER_ID)
            if not applicant_folder_id:
                print(f"Пропуск заявителя {surname} из-за ошибки при создании папки.")
                continue
                
            # Заполнение каждого шаблона
            for template_name, template_path in template_paths.items():
                # Определяем имя шаблона без расширения для поиска в маппинге
                base_template_name = os.path.splitext(template_name)[0]
                
                # Ищем соответствие в маппинге (может быть не точное совпадение, нужно уточнить логику)
                matching_mapping_key = None
                for key in mapping.keys():
                    if base_template_name.lower() in key.lower() or key.lower() in base_template_name.lower():
                        matching_mapping_key = key
                        break
                        
                if not matching_mapping_key:
                    print(f"Для шаблона {template_name} не найдено соответствия в маппинге. Пропуск.")
                    continue
                    
                # Формируем имя выходного файла
                output_filename = f"{surname}_{template_name}"
                output_path = os.path.join('filled_forms', output_filename)

                if DEBUG_INFO: print(f"Формируем файл {output_filename}")
                
                # Заполняем форму
                if fill_pdf_form(template_path, output_path, applicant_data, mapping, matching_mapping_key):
                    # Загружаем заполненную форму в папку заявителя
                    uploaded_file_id = upload_pdf_to_drive(output_path, applicant_folder_id, output_filename)
                    if uploaded_file_id:
                        print(f"Файл {output_filename} успешно загружен.")
                    else:
                        print(f"Ошибка при загрузке файла {output_filename}.")
                else:
                    print(f"Ошибка при заполнении шаблона {template_name} для {surname}.")
                    
    except Exception as e:
        print(f"Ошибка при обработке вкладок: {e}")
        
    print('Процесс завершен.')
