import zipfile
import xml.etree.ElementTree as ET

def extract():
    doc = zipfile.ZipFile('docs/Ajaya_ARCANE_PromptBook (1).docx')
    root = ET.fromstring(doc.read('word/document.xml'))
    with open('promptbook_text.txt', 'w', encoding='utf-8') as f:
        for node in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
            f.write(''.join(node.itertext()) + '\n')

if __name__ == '__main__':
    extract()
