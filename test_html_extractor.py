from processors.html_extractor import HTMLExtractor

sample_html = """
<html>
<head><title>Test Page</title></head>
<body>
    <nav>Navigation</nav>
    <h1>Eligibility</h1>
    <p>You must be 21 years old.</p>

    <h2>Income Ceiling</h2>
    <p>Your income must not exceed $14,000.</p>

    <footer>Footer content</footer>
</body>
</html>
"""

extractor = HTMLExtractor()
result = extractor.extract(sample_html, url="test")

print("TITLE:", result.title)
print("\nPLAIN TEXT:\n", result.plain_text)
print("\nSECTIONS:")
for section in result.sections:
    print(section)