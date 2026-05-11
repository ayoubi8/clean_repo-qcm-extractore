import unittest
import os
import sys
import shutil
import json
from unittest.mock import MagicMock, patch
from io import StringIO
from PIL import Image

# Force UTF-8 execution for Windows
sys.stdout.reconfigure(encoding='utf-8')

# Import our modules
from modules.ocr_processor import OCRProcessor
from modules.metadata_analyzer import MetadataAnalyzer
from modules.text_qcm_parser import TextQCMParser

class TestQCMExtractorV3(unittest.TestCase):
    
    def setUp(self):
        self.test_dir = "test_output_temp"
        os.makedirs(self.test_dir, exist_ok=True)
        
        # Create dummy page files
        self.page1_text = "Faculté de Médecine Alger\nRésidanat 2024\nModule: Cardiologie\n\nQ1. Le coeur est:\nA. Un muscle\nB. Un os\nCorrection: A"
        with open(os.path.join(self.test_dir, "page_1.txt"), "w", encoding="utf-8") as f:
            f.write(self.page1_text)
            
    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_ocr_processor_structure(self):
        """Test OCR Processor directory creation and manifest logic"""
        mock_client = MagicMock()
        # Mock response from generated_completion
        mock_client.generate_completion.return_value = {'content': "Mock OCR Text", 'usage': {'total_tokens': 100}}
        mock_client.estimate_cost.return_value = 0.001
        
        processor = OCRProcessor(mock_client, output_dir_base=self.test_dir)
        
        # Create dummy image
        img = Image.new('RGB', (100, 100))
        
        # Run process
        results = processor.process_document([img], guidance="Test Guidance")
        
        self.assertTrue(os.path.exists(results['output_dir']))
        self.assertTrue(os.path.exists(os.path.join(results['output_dir'], "page_1.txt")))
        self.assertTrue(os.path.exists(os.path.join(results['output_dir'], "manifest.json")))
        self.assertEqual(results['total_cost'], 0.001)

    def test_metadata_analyzer_logic(self):
        """Test Metadata Analyzer reading from disk"""
        mock_client = MagicMock()
        # Mock DeepSeek response
        mock_response = {
            'choices': [{'message': {'content': json.dumps({
                "source": "Alger",
                "year": 2024,
                "module": "Cardiologie",
                "domain_tag": "Medecine"
            })}}],
            'usage': {}
        }
        mock_client._call_api.return_value = mock_response
        mock_client.estimate_cost.return_value = 0.0005
        
        analyzer = MetadataAnalyzer(mock_client, 'suport/modules-bio-chir-med.json')
        
        # Run analysis on our setup directory
        result = analyzer.analyze_from_saved_ocr(self.test_dir, guidance="Test")
        print(f"\n[DEBUG] Metadata Result: {result}")
        
        self.assertEqual(result.get('module'), "Cardiologie")
        self.assertEqual(result['year'], 2024)

    def test_qcm_parser_logic(self):
        """Test parsing logic from text"""
        mock_client = MagicMock()
        mock_response = {
            'choices': [{'message': {'content': json.dumps({
                "qcms": [{
                    "number": 1,
                    "text": "Le coeur est:",
                    "propositions": {"A": "Un muscle", "B": "Un os"},
                    "correction": "A",
                    "page": 1
                }]
            })}}],
            'usage': {}
        }
        mock_client._call_api.return_value = mock_response
        
        parser = TextQCMParser(mock_client)
        metadata = {'module': 'Cardio', 'year': 2024}
        
        qcms = parser.parse_from_ocr(self.test_dir, metadata, guidance="Ignore QCS")
        
        self.assertEqual(len(qcms), 1)
        self.assertEqual(qcms[0]['text'], "Le coeur est:")
        self.assertEqual(qcms[0]['correction'], "A")

if __name__ == '__main__':
    unittest.main()
