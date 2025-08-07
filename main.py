from src import app, config
import uvicorn
import sys

def main():
    uvicorn.run(app.app, port=6969)

if __name__ == "__main__":
    main()