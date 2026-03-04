.PHONY: run

run:
	python -m uvicorn services.app:app --reload
