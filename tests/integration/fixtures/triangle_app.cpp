#include <windows.h>
#include <d3d11.h>
#include <dxgi.h>
#include <d3dcompiler.h>
#include <cstdint>
#include <string>

#include "renderdoc_app.h"

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "d3dcompiler.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "kernel32.lib")

static RENDERDOC_API_1_6_0* g_rdoc = nullptr;
static int g_capture_frame = -1;

struct VsIn {
    float pos[3];
    float col[4];
};

static const char* kHlsl = R"(
struct VSOut { float4 pos : SV_POSITION; float4 col : COLOR; };
VSOut vs_main(float3 pos : POSITION, float4 col : COLOR) {
    VSOut o;
    o.pos = float4(pos, 1.0f);
    o.col = col;
    return o;
}
float4 ps_main(VSOut i) : SV_Target {
    return i.col;
}
)";

static bool g_running = true;

LRESULT CALLBACK wndproc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_DESTROY || (m == WM_KEYDOWN && w == VK_ESCAPE)) {
        g_running = false;
        return 0;
    }
    return DefWindowProcA(h, m, w, l);
}

int main(int argc, char** argv) {
    int frames = argc > 1 ? atoi(argv[1]) : 90;
    const char* out_path = argc > 2 ? argv[2] : nullptr;

    HMODULE rdoc_mod = nullptr;
    const char* rdoc_dll = argc > 3 ? argv[3] : nullptr;
    int draws_per_frame = argc > 4 ? atoi(argv[4]) : 1;
    if (rdoc_dll) {
        rdoc_mod = LoadLibraryA(rdoc_dll);
        fprintf(stderr, "[rdoc] LoadLibrary(%s) -> %p\n", rdoc_dll, (void*)rdoc_mod);
    }
    if (!rdoc_mod) rdoc_mod = GetModuleHandleA("renderdoc.dll");
    if (rdoc_mod) {
        pRENDERDOC_GetAPI get_api =
            (pRENDERDOC_GetAPI)(void*)GetProcAddress(rdoc_mod, "RENDERDOC_GetAPI");
        if (get_api && get_api(eRENDERDOC_API_Version_1_6_0, (void**)&g_rdoc) == 1 && g_rdoc) {
            if (out_path) {
                std::string tmpl(out_path);
                size_t dot = tmpl.find_last_of(".");
                if (dot != std::string::npos) tmpl = tmpl.substr(0, dot);
                g_rdoc->SetCaptureFilePathTemplate(tmpl.c_str());
                fprintf(stderr, "[rdoc] template set: %s\n", tmpl.c_str());
            }
            if (frames >= 10) g_capture_frame = 10;
            fprintf(stderr, "[rdoc] api ready\n");
        } else {
            fprintf(stderr, "[rdoc] GetAPI failed\n");
            g_rdoc = nullptr;
        }
    }

    WNDCLASSA wc = {};
    wc.lpfnWndProc = wndproc;
    wc.hInstance = GetModuleHandleA(nullptr);
    wc.lpszClassName = "rdi_triangle";
    RegisterClassA(&wc);

    HWND hwnd = CreateWindowExA(0, "rdi_triangle", "rdi-triangle", WS_OVERLAPPEDWINDOW,
                                CW_USEDEFAULT, CW_USEDEFAULT, 640, 480,
                                nullptr, nullptr, wc.hInstance, nullptr);
    if (!hwnd) return 1;

    DXGI_SWAP_CHAIN_DESC scd = {};
    scd.BufferCount = 2;
    scd.BufferDesc.Width = 640;
    scd.BufferDesc.Height = 480;
    scd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    scd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    scd.OutputWindow = hwnd;
    scd.SampleDesc.Count = 1;
    scd.Windowed = TRUE;

    ID3D11Device* device = nullptr;
    IDXGISwapChain* swap = nullptr;
    ID3D11DeviceContext* ctx = nullptr;
    HRESULT hr = D3D11CreateDeviceAndSwapChain(
        nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0,
        nullptr, 0, D3D11_SDK_VERSION, &scd, &swap, &device, nullptr, &ctx);
    if (FAILED(hr)) return 2;

    ShowWindow(hwnd, SW_SHOWNOACTIVATE);

    ID3D11Texture2D* back = nullptr;
    swap->GetBuffer(0, __uuidof(ID3D11Texture2D), (void**)&back);
    ID3D11RenderTargetView* rtv = nullptr;
    device->CreateRenderTargetView(back, nullptr, &rtv);

    VsIn verts[3] = {
        {{-0.8f, -0.8f, 0.5f}, {1.0f, 0.0f, 0.0f, 1.0f}},
        {{0.0f, 0.9f, 0.5f}, {0.0f, 0.0f, 1.0f, 1.0f}},
        {{0.9f, -0.1f, 0.5f}, {0.0f, 1.0f, 0.0f, 1.0f}},
    };
    D3D11_BUFFER_DESC bd = {};
    bd.Usage = D3D11_USAGE_IMMUTABLE;
    bd.ByteWidth = sizeof(verts);
    bd.BindFlags = D3D11_BIND_VERTEX_BUFFER;
    D3D11_SUBRESOURCE_DATA init = {verts, 0, 0};
    ID3D11Buffer* vb = nullptr;
    device->CreateBuffer(&bd, &init, &vb);

    ID3DBlob* vs_blob = nullptr;
    ID3DBlob* err = nullptr;
    D3DCompile(kHlsl, strlen(kHlsl), nullptr, nullptr, nullptr, "vs_main", "vs_5_0", 0, 0, &vs_blob, &err);
    ID3D11VertexShader* vs = nullptr;
    device->CreateVertexShader(vs_blob->GetBufferPointer(), vs_blob->GetBufferSize(), nullptr, &vs);

    D3D11_INPUT_ELEMENT_DESC layout[] = {
        {"POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 0, D3D11_INPUT_PER_VERTEX_DATA, 0},
        {"COLOR", 0, DXGI_FORMAT_R32G32B32A32_FLOAT, 0, 12, D3D11_INPUT_PER_VERTEX_DATA, 0},
    };
    ID3D11InputLayout* il = nullptr;
    device->CreateInputLayout(layout, 2, vs_blob->GetBufferPointer(), vs_blob->GetBufferSize(), &il);

    ID3DBlob* ps_blob = nullptr;
    D3DCompile(kHlsl, strlen(kHlsl), nullptr, nullptr, nullptr, "ps_main", "ps_5_0", 0, 0, &ps_blob, &err);
    ID3D11PixelShader* ps = nullptr;
    device->CreatePixelShader(ps_blob->GetBufferPointer(), ps_blob->GetBufferSize(), nullptr, &ps);

    UINT stride = sizeof(VsIn);
    UINT offset = 0;

    D3D11_VIEWPORT vp = {0.0f, 0.0f, 640.0f, 480.0f, 0.0f, 1.0f};
    ctx->RSSetViewports(1, &vp);

    MSG msg = {};
    for (int f = 0; f < frames && g_running; ++f) {
        while (PeekMessageA(&msg, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&msg);
            DispatchMessageA(&msg);
        }

        float t = f / (float)frames;
        float clear_col[4] = {0.05f + 0.2f * t, 0.1f, 0.25f * (1.0f - t), 1.0f};
        ctx->ClearRenderTargetView(rtv, clear_col);

        ctx->OMSetRenderTargets(1, &rtv, nullptr);
        ctx->IASetInputLayout(il);
        ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        ctx->IASetVertexBuffers(0, 1, &vb, &stride, &offset);
        ctx->VSSetShader(vs, nullptr, 0);
        ctx->PSSetShader(ps, nullptr, 0);
        for (int d = 0; d < draws_per_frame; ++d) {
            ctx->Draw(3, 0);
        }

        if (g_rdoc && f == g_capture_frame) {
            g_rdoc->TriggerCapture();
            fprintf(stderr, "[rdoc] capture triggered at frame %d\n", f);
        }

        swap->Present(1, 0);
    }

    if (vb) vb->Release();
    if (il) il->Release();
    if (vs) vs->Release();
    if (ps) ps->Release();
    if (vs_blob) vs_blob->Release();
    if (ps_blob) ps_blob->Release();
    if (rtv) rtv->Release();
    if (back) back->Release();
    if (swap) swap->Release();
    if (ctx) ctx->Release();
    if (device) device->Release();
    DestroyWindow(hwnd);
    return 0;
}
