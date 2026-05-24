with open('streamlit_err.txt', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()
print("Streamlit Error Log (Last 50 lines):")
for line in lines[-50:]:
    print(line, end='')
