cmake_minimum_required(VERSION 3.20)
project(vector_engine_native VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Python3 3.9 EXACT COMPONENTS Interpreter Development REQUIRED)

add_library(vector_engine_native MODULE
    src/stroke_tessellation.cpp
    src/visibility.cpp
    src/mesh_extrusion.cpp
    src/software_rasterizer.cpp
    python_bindings/module.cpp
)
target_include_directories(vector_engine_native PRIVATE include)
target_link_libraries(vector_engine_native PRIVATE Python3::Python)

if(MSVC)
    target_compile_options(vector_engine_native PRIVATE /W4 /permissive- /EHsc)
endif()

set_target_properties(vector_engine_native PROPERTIES
    PREFIX ""
    SUFFIX ".pyd"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/bin"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/bin"
    LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/bin"
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/bin"
)
