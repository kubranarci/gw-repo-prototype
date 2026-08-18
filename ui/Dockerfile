FROM python:3.12-slim

WORKDIR /code

# Install streamlit, plotly, requests, pandas, and python-dotenv directly 
# without needing heavy database compilation tools in the UI container
RUN pip install --no-cache-dir streamlit plotly requests pandas python-dotenv

COPY . .

CMD ["streamlit", "run", "ui/app.py", "--server.address=0.0.0.0", "--server.port=8501"]