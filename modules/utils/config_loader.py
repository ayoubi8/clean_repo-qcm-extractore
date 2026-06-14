import yaml
import os
from pathlib import Path
from typing import Dict, Any, Optional

class ConfigLoader:
    """Load and validate batch processing configuration."""
    
    def __init__(self, config_path: str = "batch_config.yaml"):
        # Use absolute path relative to current file if needed, 
        # but here we'll stick to the provided path or CWD
        self.config_path = Path(config_path)
        self.config = None
        
    def load(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
            
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
            
        self._validate()
        return self.config
    
    def _validate(self):
        """Validate configuration structure and values."""
        if not self.config:
            return
            
        required_sections = ['batch_mode', 'extraction', 'metadata', 'corrections']
        
        for section in required_sections:
            if section not in self.config:
                raise ValueError(f"Missing required section: '{section}' in config file")
        
        # Validate extraction method
        valid_methods = ['vision_ocr', 'pypdfium2']
        if self.config.get('extraction', {}).get('method') not in valid_methods:
            method = self.config.get('extraction', {}).get('method')
            print(f"⚠️ Warning: Invalid extraction method '{method}'. Defaulting to 'vision_ocr'")
            if 'extraction' not in self.config: self.config['extraction'] = {}
            self.config['extraction']['method'] = 'vision_ocr'
        
        # Success log
        # print("✅ Configuration validated successfully")
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """Get nested config value using dot notation (e.g., 'metadata.fields.year.strategy')."""
        if not self.config:
            try:
                self.load()
            except:
                return default
                
        keys = key_path.split('.')
        value = self.config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def create_template(self, output_path: str = "batch_config_template.yaml"):
        """Create a template configuration file."""
        template_content = """# Batch Processing Configuration Template
# Copy this file to batch_config.yaml and customize

batch_mode:
  enabled: true
  pause_for_verification: false

# Step 1: Text Extraction
extraction:
  method: "vision_ocr"
  ocr_guidance: "Two-column layout, ignore headers/footers"
  model: "google/gemini-2.0-flash-lite-001"

# Step 2: QCM Extraction
qcm_extraction:
  page_range: "all"
  model_primary: "google/gemini-2.5-flash-lite-preview-09-2025"
  model_fallback: "google/gemini-2.0-flash-lite-001"

# Step 3: Metadata
metadata:
  detection_mode: "ai_auto"
  fields:
    year:
      strategy: "per_qcm"
      value: null
    source:
      strategy: "global"
      value: "Source Name"
    category:
      strategy: "ai_detect"
      value: null
    subcategory:
      strategy: "skip"
      value: null
  global_pages: [1]

# Step 4: Format Template
template:
  auto_select: true
  name: "default"

# Step 6: Corrections
corrections:
  source: "page_text"
  pages: []
  ai_mode: "sequential"
  model: "deepseek/deepseek-r1-distill-llama-70b"

# Folder Batch Processing
folder_batch:
  enabled: false
  input_folder: "./input"
  file_pattern: "*.pdf"
  output_base: "output/batch_results"
"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template_content)
        
        print(f"✅ Template created: {output_path}")
