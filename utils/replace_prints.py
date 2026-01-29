#!/usr/bin/env python3
"""
Script to replace all print statements with logger calls in main.py
This ensures all logs are captured and displayed in the UI
"""

import re

# Read the file
with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Patterns to replace print statements with logger calls
replacements = [
    # COUPON related
    (r'print\(f?"\[COUPON\](.*?)"\)', r'self.logger.info(r"\1")'),
    (r'print\("\[COUPON\](.*?)"\)', r'self.logger.info(r"\1")'),
    (r'print\(f?"\[COUPON\] ✅ (.*?)"\)', r'self.logger.success(r"\1")'),
    (r'print\(f?"\[COUPON\] ❌ (.*?)"\)', r'self.logger.error(r"\1")'),
    
    # [4] PRODUCT related
    (r'print\(f?"\[4\](.*?)"\)', r'self.logger.info(r"\1")'),
    (r'print\("\[4\](.*?)"\)', r'self.logger.info(r"\1")'),
    
    # DEALS related
    (r'print\(f?"\[DEALS\](.*?)"\)', r'self.logger.info(r"\1")'),
    (r'print\("\[DEALS\](.*?)"\)', r'self.logger.info(r"\1")'),
    
    # CHECKOUT related
    (r'print\(f?"\[CHECKOUT\](.*?)"\)', r'self.logger.info(r"\1")'),
    (r'print\("\[CHECKOUT\](.*?)"\)', r'self.logger.info(r"\1")'),
    
    # LOGIN/OTP related
    (r'print\(f?"\[LOGIN\](.*?)"\)', r'self.logger.info(r"\1")'),
    (r'print\(f?"\[OTP\](.*?)"\)', r'self.logger.info(r"\1")'),
    (r'print\("\[1\](.*?)"\)', r'self.logger.info(r"\1")'),
]

# Apply replacements
for pattern, replacement in replacements:
    content = re.sub(pattern, replacement, content)

# Write back
with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done replacing print statements!")



