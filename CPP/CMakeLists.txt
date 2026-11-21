cmake_minimum_required(VERSION 3.20)
project(FEARFilesDesktop LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 REQUIRED COMPONENTS Widgets OpenGLWidgets)
find_package(Qt6 QUIET COMPONENTS Pdf PdfWidgets)
find_package(OpenSSL REQUIRED)
find_package(ZLIB QUIET)
find_package(PkgConfig REQUIRED)
pkg_check_modules(MPV REQUIRED mpv)

add_executable(fearfiles_desktop fearfiles_desktop.cpp)
target_include_directories(fearfiles_desktop PRIVATE ${MPV_INCLUDE_DIRS})
target_link_libraries(fearfiles_desktop PRIVATE
    Qt6::Widgets
    Qt6::OpenGLWidgets
    OpenSSL::Crypto
    ${MPV_LIBRARIES}
)

if(Qt6PdfWidgets_FOUND)
    target_link_libraries(fearfiles_desktop PRIVATE Qt6::Pdf Qt6::PdfWidgets)
    target_compile_definitions(fearfiles_desktop PRIVATE HAVE_QT_PDF=1)
endif()

if(ZLIB_FOUND)
    target_link_libraries(fearfiles_desktop PRIVATE ZLIB::ZLIB)
    target_compile_definitions(fearfiles_desktop PRIVATE HAVE_ZLIB=1)
endif()

if(WIN32)
    target_link_libraries(fearfiles_desktop PRIVATE advapi32 user32)
endif()