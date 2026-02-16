from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject, DictionaryObject, ArrayObject, NumberObject, IndirectObject

import re

def analyze_pdf_structure(pdf_path):
    """Детальный анализ структуры PDF"""
    # print(f="=== АНАЛИЗ PDF: {pdf_path} ===")
    
    reader = PdfReader(pdf_path)
    
    # 1. Базовая информация
    print(f"\n1. ОСНОВНАЯ ИНФОРМАЦИЯ:")
    print(f"   Страниц: {len(reader.pages)}")
    print(f"   Метadata: {reader.metadata}")
    
    # 2. Проверка на XFA
    print(f"\n2. ПРОВЕРКА НА XFA:")
    if '/Root' in reader.trailer:
        root = reader.trailer['/Root']
        if '/AcroForm' in root:
            acroform = root['/AcroForm']
            print(f"   AcroForm найден")
            if '/XFA' in acroform:
                print(f"   ✅ Это XFA-форма (XML Forms Architecture)")
                print(f"   XFA данные: {type(acroform['/XFA'])}")
            else:
                print(f"   Это AcroForm (стандартная форма)")
        else:
            print(f"   ❌ AcroForm не найден")
    
    # 3. Проверка аннотаций на первой странице
    print(f"\n3. АННОТАЦИИ НА ПЕРВОЙ СТРАНИЦЕ:")
    if len(reader.pages) > 0:
        page = reader.pages[0]
        if '/Annots' in page:
            annots = page['/Annots']
            print(f"   Найдено аннотаций: {len(annots)}")
            
            for i, annot in enumerate(annots[:5]):  # Первые 5
                print(f"\n   Аннотация {i}:")
                print(f"     Тип: {type(annot)}")
                
                # Пробуем получить содержимое разными способами
                try:
                    if hasattr(annot, 'get_object'):
                        obj = annot.get_object()
                        print(f"     get_object(): {type(obj)}")
                        if isinstance(obj, dict):
                            print(f"     Ключи: {list(obj.keys())}")
                except:
                    pass
                
                try:
                    if hasattr(reader, '_get_object') and hasattr(annot, 'idnum'):
                        obj = reader._get_object(annot.idnum, 0)
                        print(f"     _get_object(): {type(obj)}")
                        if isinstance(obj, dict):
                            print(f"     Ключи: {list(obj.keys())}")
                except:
                    pass
        else:
            print("   ❌ Нет аннотаций на странице")
    
    # 4. Поиск полей через raw данные
    print(f"\n4. ПОИСК ПОЛЕЙ В RAW ДАННЫХ:")
    try:
        with open(pdf_path, 'rb') as f:
            content = f.read().decode('latin-1', errors='ignore')
            
            # Ищем признаки полей формы
            patterns = {
                'TextField': r'/Tx\b',
                'CheckBox': r'/Btn\b',
                'RadioButton': r'/Btn\b.*?/Ff\s+(\d+)',
                'FieldName': r'/T\s*\(([^)]+)\)',
                'FieldValue': r'/V\s*\(([^)]+)\)',
            }
            
            for name, pattern in patterns.items():
                matches = re.findall(pattern, content)
                if matches:
                    print(f"   {name}: найдено {len(matches)}")
                    if name == 'FieldName' and matches:
                        print(f"     Примеры: {matches[:5]}")
    except Exception as e:
        print(f"   Ошибка при чтении raw данных: {e}")

# Используйте функцию




def restore_acroform_from_annotations(input_pdf, output_pdf):
    """
    ПОЛНОЕ восстановление структуры /AcroForm с сохранением всех атрибутов полей.
    """
    try:
        import os
        if not os.path.exists(input_pdf):
            print(f"❌ Ошибка: Файл '{input_pdf}' не найден!")
            return False
        
        print(f"📖 Читаем файл: {input_pdf}")
        reader = PdfReader(input_pdf)
        writer = PdfWriter()
        
        # Копируем все страницы
        for page in reader.pages:
            writer.add_page(page)
        
        # Словарь для хранения всех полей
        all_fields = {}
        field_refs = {}  # Для хранения ссылок на поля
        
        # Сначала соберем все поля через get_fields() из reader
        print("\n🔍 Получаем поля через reader.get_fields():")
        original_fields = reader.get_fields()
        
        if original_fields:
            print(f"✅ Найдено {len(original_fields)} полей в оригинале")
            for field_name, field in original_fields.items():
                print(f"  - {field_name}: {field.get('/FT', 'тип не указан')}")
                # Сохраняем информацию о полях
                all_fields[field_name] = field
        else:
            print("❌ reader.get_fields() не нашел поля!")
            print("Пробуем извлечь поля из аннотаций...")
            
            # Если get_fields не работает, извлекаем из аннотаций
            for page_num, page in enumerate(writer.pages):
                if '/Annots' not in page:
                    continue
                    
                for annot_ref in page['/Annots']:
                    if hasattr(annot_ref, 'get_object'):
                        annot = annot_ref.get_object()
                    else:
                        annot = annot_ref
                    
                    if isinstance(annot, dict):
                        if '/T' in annot:
                            field_name = str(annot['/T'])
                            all_fields[field_name] = annot
        
        if not all_fields:
            print("❌ Не удалось найти поля!")
            return False
        
        print(f"\n✅ Всего найдено полей: {len(all_fields)}")
        
        # Создаем правильную структуру AcroForm
        acroform = DictionaryObject()
        fields_array = ArrayObject()
        
        # Создаем новые объекты полей с правильными ссылками
        for field_name, field in all_fields.items():
            # Создаем копию поля со всеми атрибутами
            field_copy = DictionaryObject()
            
            # Копируем ВСЕ атрибуты поля
            important_keys = [
                '/FT', '/T', '/V', '/DV', '/Ff', '/Rect',
                '/AP', '/AS', '/BS', '/Border', '/DA',
                '/H', '/MK', '/Subtype', '/Type', '/TU',
                '/MaxLen', '/Q', '/Opt', '/TI', '/I'
            ]
            
            for key in important_keys:
                if key in field:
                    try:
                        field_copy[key] = field[key]
                    except:
                        pass
            
            # Обязательно добавляем тип поля, если его нет
            if '/FT' not in field_copy:
                if '/Btn' in str(field.get('/FT', '')):
                    field_copy[NameObject('/FT')] = NameObject('/Btn')
                else:
                    field_copy[NameObject('/FT')] = NameObject('/Tx')
            
            # Добавляем ссылку на страницу (важно!)
            if hasattr(field, 'indirect_reference'):
                field_copy[NameObject('/P')] = field.indirect_reference
            
            fields_array.append(field_copy)
            field_refs[field_name] = field_copy
        
        # Добавляем поля в AcroForm
        acroform[NameObject('/Fields')] = fields_array
        
        # Добавляем ВСЕ необходимые ресурсы
        dr_dict = DictionaryObject()
        font_dict = DictionaryObject()
        
        # Стандартные шрифты PDF
        helv = DictionaryObject()
        helv[NameObject('/Type')] = NameObject('/Font')
        helv[NameObject('/Subtype')] = NameObject('/Type1')
        helv[NameObject('/BaseFont')] = NameObject('/Helvetica')
        font_dict[NameObject('/Helv')] = helv
        
        za_db = DictionaryObject()
        za_db[NameObject('/Type')] = NameObject('/Font')
        za_db[NameObject('/Subtype')] = NameObject('/Type1')
        za_db[NameObject('/BaseFont')] = NameObject('/ZapfDingbats')
        font_dict[NameObject('/ZaDb')] = za_db
        
        # Добавляем Courier для текстовых полей
        cour = DictionaryObject()
        cour[NameObject('/Type')] = NameObject('/Font')
        cour[NameObject('/Subtype')] = NameObject('/Type1')
        cour[NameObject('/BaseFont')] = NameObject('/Courier')
        font_dict[NameObject('/Cour')] = cour
        
        dr_dict[NameObject('/Font')] = font_dict
        
        # Добавляем ресурсы в AcroForm
        acroform[NameObject('/DR')] = dr_dict
        
        # Обязательные атрибуты для корректного отображения
        acroform[NameObject('/NeedAppearances')] = NameObject('/True')
        acroform[NameObject('/DA')] = TextStringObject('/Helv 10 Tf 0 g')
        acroform[NameObject('/Q')] = NumberObject(0)  # Выравнивание по левому краю
        
        # Добавляем AcroForm в корень документа
        writer._root_object[NameObject('/AcroForm')] = acroform
        
        # Обновляем аннотации на страницах с ссылками на поля
        print("\n🔄 Обновляем аннотации на страницах...")
        
        for page_num, page in enumerate(writer.pages):
            if '/Annots' in page:
                new_annots = ArrayObject()
                
                for annot_ref in page['/Annots']:
                    if hasattr(annot_ref, 'get_object'):
                        annot = annot_ref.get_object()
                    else:
                        annot = annot_ref
                    
                    if isinstance(annot, dict) and '/T' in annot:
                        field_name = str(annot['/T'])
                        if field_name in field_refs:
                            # Заменяем аннотацию ссылкой на наше поле
                            new_annots.append(field_refs[field_name])
                        else:
                            new_annots.append(annot_ref)
                    else:
                        new_annots.append(annot_ref)
                
                page[NameObject('/Annots')] = new_annots
        
        # Сохраняем результат
        print("\n💾 Сохраняем файл...")
        with open(output_pdf, 'wb') as f:
            writer.write(f)
        
        print(f"✅ Файл сохранен: {output_pdf}")
        
        # Финальная проверка
        print("\n🔍 Финальная проверка:")
        test_reader = PdfReader(output_pdf)
        restored_fields = test_reader.get_fields()
        
        if restored_fields:
            print(f"✅ ПОЛНОСТЬЮ РАБОТАЕТ! get_fields() видит {len(restored_fields)} полей:")
            for name, field in restored_fields.items():
                field_type = field.get('/FT', 'неизвестно')
                print(f"  - {name}: {field_type}")
                
                # Проверяем чек-боксы
                if field_type == '/Btn':
                    print(f"    ✓ Это чек-бокс/радио-кнопка")
                    if '/V' in field:
                        print(f"    Значение: {field['/V']}")
        else:
            print("❌ Критическая ошибка: get_fields() не видит поля!")
            print("Пробуем альтернативный метод сохранения...")
            
            # Альтернативный метод: копируем весь reader
            writer = PdfWriter(clone_from=reader)
            with open(output_pdf, 'wb') as f:
                writer.write(f)
            
            test_reader = PdfReader(output_pdf)
            if test_reader.get_fields():
                print(f"✅ Альтернативный метод сработал! Поля восстановлены.")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject, DictionaryObject, ArrayObject, NumberObject

def create_acroform_with_real_names(input_pdf, output_pdf):
    """
    СОЗДАЕТ AcroForm и переименовывает поля в соответствии с их метками.
    """
    try:
        import os
        if not os.path.exists(input_pdf):
            print(f"❌ Ошибка: Файл '{input_pdf}' не найден!")
            return False
        
        print(f"📖 Читаем файл: {input_pdf}")
        reader = PdfReader(input_pdf)
        writer = PdfWriter()
        
        # Копируем все страницы
        for page in reader.pages:
            writer.add_page(page)
        
        # Словарь для хранения информации о полях
        fields_list = []  # список всех полей с их данными
        
        print("\n🔍 Анализируем аннотации...")
        
        # Определяем соответствие между позициями и названиями полей
        # (примерные координаты, нужно подстроить под ваш файл)
        field_mapping = {
            # Левая колонка
            (100, 700): "Nombre",      # Примерные координаты
            (100, 670): "Nacionalidad",
            (100, 640): "Fecha_nacimiento",
            (100, 610): "Nombre_padre",
            (100, 580): "Domicilio_Espana",
            (100, 550): "Localidad",
            (100, 520): "Telefono",
            (100, 490): "Representante_legal",
            
            # Средняя колонка
            (300, 700): "1er_Apellido",
            (300, 670): "NIE",
            (300, 640): "Localidad_nacimiento",
            (300, 610): "Nombre_madre",
            (300, 580): "CP",
            (300, 550): "Email",
            (300, 520): "NIF_representante",
            (300, 490): "Provincia",
            
            # Правая колонка
            (500, 700): "2o_Apellido",
            (500, 670): "Pasaporte",
            (500, 640): "Pais_nacimiento",
            (500, 610): "Estado_civil",
            (500, 580): "Numero",
            (500, 550): "Piso",
            (500, 520): "Titulo",
        }
        
        for page_num, page in enumerate(writer.pages):
            if '/Annots' not in page:
                continue
            
            annots = page['/Annots']
            
            for i, annot_ref in enumerate(annots):
                # Получаем объект аннотации
                if hasattr(annot_ref, 'get_object'):
                    annot = annot_ref.get_object()
                else:
                    annot = annot_ref
                
                if not isinstance(annot, dict):
                    continue
                
                # Получаем координаты поля
                rect = annot.get('/Rect', None)
                if rect and len(rect) == 4:
                    # Координаты: [x1, y1, x2, y2] - левый нижний и правый верхний углы
                    x = (rect[0] + rect[2]) / 2  # средняя точка по X
                    y = (rect[1] + rect[3]) / 2  # средняя точка по Y
                    
                    print(f"  📍 Поле {i}: координаты ({x:.0f}, {y:.0f})")
                    
                    # Определяем имя поля по ближайшей метке
                    field_name = None
                    min_distance = 50  # максимальное расстояние в пикселях
                    
                    for (mx, my), name in field_mapping.items():
                        distance = ((x - mx) ** 2 + (y - my) ** 2) ** 0.5
                        if distance < min_distance:
                            min_distance = distance
                            field_name = name
                    
                    if field_name:
                        print(f"     → соответствует: {field_name}")
                        
                        # Меняем имя поля
                        if '/T' in annot:
                            old_name = annot['/T']
                            annot[NameObject('/T')] = TextStringObject(field_name)
                            print(f"       переименовано: {old_name} -> {field_name}")
                        
                        fields_list.append({
                            'annot': annot,
                            'annot_ref': annot_ref,
                            'name': field_name,
                            'rect': rect,
                            'page': page_num
                        })
                    else:
                        # Если не нашли соответствие, оставляем старое имя
                        field_name = annot.get('/T', f'field_{i}')
                        print(f"     → неизвестное поле: {field_name}")
                        fields_list.append({
                            'annot': annot,
                            'annot_ref': annot_ref,
                            'name': field_name,
                            'rect': rect,
                            'page': page_num
                        })
        
        if not fields_list:
            print("❌ Нет полей для создания формы!")
            return False
        
        print(f"\n✅ Найдено {len(fields_list)} полей")
        
        # Группируем поля по именам
        fields_by_name = {}
        for field in fields_list:
            name = field['name']
            if name not in fields_by_name:
                fields_by_name[name] = []
            fields_by_name[name].append(field)
        
        print(f"\n📋 Сгруппировано {len(fields_by_name)} уникальных полей:")
        for name, instances in fields_by_name.items():
            print(f"  - {name}: {len(instances)} аннотаций")
        
        # СОЗДАЕМ AcroForm
        acroform = DictionaryObject()
        fields_array = ArrayObject()
        
        # Добавляем все поля в массив
        for field in fields_list:
            fields_array.append(field['annot_ref'])
        
        # Добавляем поля в AcroForm
        acroform[NameObject('/Fields')] = fields_array
        
        # Добавляем ресурсы
        dr_dict = DictionaryObject()
        font_dict = DictionaryObject()
        
        helv = DictionaryObject()
        helv[NameObject('/Type')] = NameObject('/Font')
        helv[NameObject('/Subtype')] = NameObject('/Type1')
        helv[NameObject('/BaseFont')] = NameObject('/Helvetica')
        font_dict[NameObject('/Helv')] = helv
        
        za_db = DictionaryObject()
        za_db[NameObject('/Type')] = NameObject('/Font')
        za_db[NameObject('/Subtype')] = NameObject('/Type1')
        za_db[NameObject('/BaseFont')] = NameObject('/ZapfDingbats')
        font_dict[NameObject('/ZaDb')] = za_db
        
        dr_dict[NameObject('/Font')] = font_dict
        acroform[NameObject('/DR')] = dr_dict
        acroform[NameObject('/NeedAppearances')] = NameObject('/True')
        acroform[NameObject('/DA')] = TextStringObject('/Helv 10 Tf 0 g')
        
        # Добавляем AcroForm в корень документа
        if hasattr(writer, '_root'):
            writer._root[NameObject('/AcroForm')] = acroform
        elif hasattr(writer, '_root_object'):
            writer._root_object[NameObject('/AcroForm')] = acroform
        
        # Сохраняем
        print("\n💾 Сохраняем файл...")
        with open(output_pdf, 'wb') as f:
            writer.write(f)
        
        print(f"✅ Файл сохранен: {output_pdf}")
        
        # ПРОВЕРКА
        print("\n🔍 ПРОВЕРКА ПЕРЕИМЕНОВАННЫХ ПОЛЕЙ:")
        test_reader = PdfReader(output_pdf)
        
        try:
            fields = test_reader.get_fields()
            if fields:
                print(f"✅ Найдено {len(fields)} полей:")
                
                # Проверяем наличие основных полей
                expected_fields = [
                    "Nombre", "1er_Apellido", "2o_Apellido",
                    "Nacionalidad", "NIE", "Pasaporte",
                    "Fecha_nacimiento", "Localidad_nacimiento", "Pais_nacimiento",
                    "Nombre_padre", "Nombre_madre", "Estado_civil",
                    "Domicilio_Espana", "Numero", "Piso",
                    "Localidad", "CP", "Provincia",
                    "Telefono", "Email", "Titulo",
                    "Representante_legal", "NIF_representante"
                ]
                
                found_count = 0
                for expected in expected_fields:
                    if expected in fields:
                        print(f"  ✅ {expected}")
                        found_count += 1
                    else:
                        print(f"  ❌ {expected}")
                
                print(f"\n📊 Итого: найдено {found_count} из {len(expected_fields)} ожидаемых полей")
            else:
                print("❌ get_fields() не нашел полей!")
        except Exception as e:
            print(f"❌ Ошибка при проверке: {e}")
        
        print("\n✨ Готово! Файл сохранен с правильными именами полей.")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False

# Использование
if __name__ == "__main__":
    input_file = r"C:\Users\Admin\OneDrive\Проекты\ВНЖ\Шаблоны\Декларация_о_въезде.pdf"
    output_file = r"declaracion_nombres_correctos.pdf"
    
    print("🔄 ПЕРЕИМЕНОВАНИЕ ПОЛЕЙ ПО ИХ ПОЗИЦИИ")
    print("=" * 50)
    create_acroform_with_real_names(input_file, output_file)
    # restore_acroform_from_annotations(input_file, output_file)
    # analyze_pdf_structure(input_file)