# from contextlib import asynccontextmanager

# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware

# from app.database import engine
# from app.routes.destinations import router as destinations_router


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     yield
#     await engine.dispose()


# app = FastAPI(
#     title="AccessMelb API",
#     description="Accessibility infrastructure API for Melbourne destinations",
#     lifespan=lifespan,
# )

# # allow frontend on any port during development
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine
from app.routes.destinations import router as destinations_router
from app.routes.journeys import router as journeys_router
from app.routes.old_destinations import router as old_destinations_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="AccessMelb API",
    description="Accessibility infrastructure API for Melbourne destinations",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "AccessMelb API is running"}

app.include_router(destinations_router)
app.include_router(journeys_router)
app.include_router(old_destinations_router)