FROM python:3.8.0

RUN git clone https://github.com/skvrd/syncer

RUN pip install pipenv
WORKDIR syncer
COPY config.yml .

RUN pipenv install
CMD pipenv run python script.py