import os
import distutils.errors

try:
    import distutils.msvc9compiler
except ImportError:
    pass

unpatched = dict()

def patch_for_specialized_compiler():
    """
    Patch functions in distutils.msvc9compiler to use the standalone compiler
    build for Python (Windows only). Fall back to original behavior when the
    standalone compiler is not available.
    """
    if 'distutils' not in globals():
        # The module isn't available to be patched
        return

    if unpatched:
        # Already patched
        return

    unpatched.update(vars(distutils.msvc9compiler))

    distutils.msvc9compiler.find_vcvarsall = find_vcvarsall
    distutils.msvc9compiler.query_vcvarsall = query_vcvarsall

def find_vcvarsall(version):
    Reg = distutils.msvc9compiler.Reg
    VC_BASE = r'Software\%sMicrosoft\DevDiv\VCForPython\%0.1f'
    key = VC_BASE % ('', version)
    try:
        # Per-user installs register the compiler path here
        productdir = Reg.get_value(key, "installdir")
    except KeyError:
        try:
            # All-user installs on a 64-bit system register here
            key = VC_BASE % ('Wow6432Node\\', version)
            productdir = Reg.get_value(key, "installdir")
        except KeyError:
            productdir = None

    if productdir:
        vcvarsall = os.path.os.path.join(productdir, "vcvarsall.bat")
        if os.path.isfile(vcvarsall):
            return vcvarsall

    return unpatched['find_vcvarsall'](version)

def query_vcvarsall(version, arch='x86', *args, **kwargs):
    message = ''

    # Try to get environement from vcvarsall.bat (Classical way)
    try:
        return unpatched['query_vcvarsall'](version, arch, *args, **kwargs)
    except distutils.errors.DistutilsPlatformError as exc:
        # Error if Vcvarsall.bat is missing
        message = exc.args[0]
    except ValueError as exc:
        # Error if environment not set after executing vcvarsall.bat
        message = exc.args[0]

    # If vcvarsall.bat fail, try to set environment directly
    try:
        return _query_vcvarsall(version, arch)
    except distutils.errors.DistutilsPlatformError as exc:
        # Error if MSVC++ directory not found or environment not set
        message = exc.args[0]

    # Raise error
    if message and "vcvarsall.bat" in message:
        # Special error message if MSVC++ not installed
        message = 'Microsoft Visual C++ %0.1f is required (%s).' %\
            (version, message)
        if int(version) == 9:
            # For VC++ 9.0 Redirect user to Vc++ for Python 2.7 :
            # This redirection link is maintained by Microsoft.
            # Contact vspython@microsoft.com if it needs updating.
            message += r' Get it from http://aka.ms/vcpython27'
        elif int(version) == 10:
            # For VC++ 10.0 Redirect user to Windows SDK 7.1
            message += ' Get it with "Microsoft Windows SDK for Windows 7": '
            message += r'www.microsoft.com/download/details.aspx?id=8279'

    raise distutils.errors.DistutilsPlatformError(message)


class PlatformInfo:
    current_cpu = os.environ['processor_architecture'].lower()

    def __init__(self, arch):
        self.arch = arch

    @property
    def target_cpu(self):
        return self.arch[self.arch.find('_') + 1:]

    def target_is_x86(self):
        return self.target_cpu == 'x86'

    def current_is_x86(self):
        return self.current_cpu != 'x86'

    @property
    def lib_extra(self):
        return (
            r'\amd64' if self.target_cpu == 'amd64' else
            r'\ia64' if self.target_cpu == 'ia64' else
            ''
        )

    @property
    def sdk_extra(self):
        return (
            r'\x64' if self.target_cpu == 'amd64' else
            r'\ia64' if self.target_cpu == 'ia64' else
            ''
        )

    @property
    def tools_extra(self):
        path = self.lib_extra
        if self.target_cpu != self.current_cpu:
            path = path.replace('\\', '\\x86_')
        return path


def _query_vcvarsall(version, arch):
    """
    Return environment variables for specified Microsoft Visual C++ version
    and platform.
    """
    pi = PlatformInfo(arch)

    # Find "Windows" and "Program Files" system directories
    WinDir = os.environ['WinDir']
    ProgramFiles = os.environ['ProgramFiles']
    ProgramFilesX86 = os.environ.get('ProgramFiles(x86)', ProgramFiles)

    # Set registry base paths
    reg_value = distutils.msvc9compiler.Reg.get_value
    node = r'\Wow6432Node' if not pi.current_is_x86() else ''
    VsReg = r'Software%s\Microsoft\VisualStudio\SxS\VS7' % node
    VcReg = r'Software%s\Microsoft\VisualStudio\SxS\VC7' % node
    VcForPythonReg = r'Software%s\Microsoft\DevDiv\VCForPython\%0.1f' %\
        (node, version)
    WindowsSdkReg = r'Software%s\Microsoft\Microsoft SDKs\Windows' % node

    # Find Microsoft Visual Studio directory
    try:
        # Try to get it from registry
        VsInstallDir = reg_value(VsReg, '%0.1f' % version)
    except KeyError:
        # If fail, use default path
        name = 'Microsoft Visual Studio %0.1f' % version
        VsInstallDir = os.path.join(ProgramFilesX86, name)

    # Find Microsoft Visual C++ directory
    try:
        # Try to get it from registry
        VcInstallDir = reg_value(VcReg, '%0.1f' % version)
    except KeyError:
        try:
            # Try to get "VC++ for Python" version from registry
            install_base = reg_value(VcForPythonReg, 'installdir')
            VcInstallDir = os.path.join(install_base, 'VC')
        except KeyError:
            # If fail, use default path
            default = r'Microsoft Visual Studio %0.1f\VC' % version
            VcInstallDir = os.path.join(ProgramFilesX86, default)
    if not os.path.isdir(VcInstallDir):
        msg = 'vcvarsall.bat and Visual C++ directory not found'
        raise distutils.errors.DistutilsPlatformError(msg)

    # Find Microsoft Windows SDK directory
    WindowsSdkDir = ''
    if version == 9.0:
        WindowsSdkVer = ('7.0', '6.1', '6.0a')
    elif version == 10.0:
        WindowsSdkVer = ('7.1', '7.0a')
    else:
        WindowsSdkVer = ()
    for ver in WindowsSdkVer:
        # Try to get it from registry
        try:
            loc = os.path.join(WindowsSdkReg, 'v%s' % ver)
            WindowsSdkDir = reg_value(loc, 'installationfolder')
            break
        except KeyError:
            pass
    if not WindowsSdkDir or not os.path.isdir(WindowsSdkDir):
        # Try to get "VC++ for Python" version from registry
        try:
            install_base = reg_value(VcForPythonReg, 'installdir')
            WindowsSdkDir = os.path.join(install_base, 'WinSDK')
        except:
            pass
    if not WindowsSdkDir or not os.path.isdir(WindowsSdkDir):
        # If fail, use default path
        for ver in WindowsSdkVer:
            path = r'Microsoft SDKs\Windows\v%s' % ver
            d = os.path.join(ProgramFiles, path)
            if os.path.isdir(d):
                WindowsSdkDir = d
    if not WindowsSdkDir:
        # If fail, use Platform SDK
        WindowsSdkDir = os.path.join(VcInstallDir, 'PlatformSDK')

    # Find Microsoft .NET Framework 32bit directory
    try:
        # Try to get it from registry
        FrameworkDir32 = reg_value(VcReg, 'frameworkdir32')
    except KeyError:
        # If fail, use default path
        FrameworkDir32 = os.path.join(WinDir, r'Microsoft.NET\Framework')

    # Find Microsoft .NET Framework 64bit directory
    try:
        # Try to get it from registry
        FrameworkDir64 = reg_value(VcReg, 'frameworkdir64')
    except KeyError:
        # If fail, use default path
        FrameworkDir64 = os.path.join(WinDir, r'Microsoft.NET\Framework64')

    # Find Microsoft .NET Framework Versions
    if version == 10.0:
        try:
            # Try to get v4 from registry
            v4 = reg_value(VcReg, 'frameworkver32')
            if v4.lower()[:2] != 'v4':
                raise KeyError('Not the V4')
        except KeyError:
            # If fail, use last v4 version
            v4 = 'v4.0.30319'
        FrameworkVer = (v4, 'v3.5')
    elif version == 9.0:
        FrameworkVer = ('v3.5', 'v2.0.50727')
    elif version == 8.0:
        FrameworkVer = ('v3.0', 'v2.0.50727')

    # Set Microsoft Visual Studio Tools
    VSTools = [os.path.join(VsInstallDir, r'Common7\IDE'),
               os.path.join(VsInstallDir, r'Common7\Tools')]

    # Set Microsoft Visual C++ Includes
    VCIncludes = [os.path.join(VcInstallDir, 'Include')]

    # Set Microsoft Visual C++ & Microsoft Foundation Class Libraries
    VCLibraries = [
        os.path.join(VcInstallDir, 'Lib' + pi.lib_extra),
        os.path.join(VcInstallDir, r'ATLMFC\LIB' + pi.lib_extra),
    ]

    # Set Microsoft Visual C++ Tools
    VCTools = [
        os.path.join(VcInstallDir, 'VCPackages'),
        os.path.join(VcInstallDir, 'Bin' + pi.tools_extra),
    ]
    if pi.tools_extra:
        VCTools.append(os.path.join(VcInstallDir, 'Bin'))

    # Set Microsoft Windows SDK Include
    OSLibraries = [os.path.join(WindowsSdkDir, 'Lib' + pi.sdk_extra)]

    # Set Microsoft Windows SDK Libraries
    OSIncludes = [
        os.path.join(WindowsSdkDir, 'Include'),
        os.path.join(WindowsSdkDir, r'Include\gl'),
    ]

    # Set Microsoft Windows SDK Tools
    SdkTools = [os.path.join(WindowsSdkDir, 'Bin')]
    if not pi.target_is_x86():
        SdkTools.append(os.path.join(WindowsSdkDir, 'Bin' + pi.sdk_extra))
    if version == 10.0:
        path = r'Bin\NETFX 4.0 Tools' + pi.sdk_extra
        SdkTools.append(os.path.join(WindowsSdkDir, path))

    # Set Microsoft Windows SDK Setup
    SdkSetup = [os.path.join(WindowsSdkDir, 'Setup')]

    # Set Microsoft .NET Framework Tools
    FxTools = [os.path.join(FrameworkDir32, ver) for ver in FrameworkVer]
    if not pi.target_is_x86() and not pi.current_is_x86():
        for ver in FrameworkVer:
            FxTools.append(os.path.join(FrameworkDir64, ver))

    # Set Microsoft Visual Studio Team System Database
    VsTDb = [os.path.join(VsInstallDir, r'VSTSDB\Deploy')]

    # Return Environment Variables
    env = {}
    env['include'] = [VCIncludes, OSIncludes]
    env['lib'] = [VCLibraries, OSLibraries, FxTools]
    env['libpath'] = [VCLibraries, FxTools]
    env['path'] = [VCTools, VSTools, VsTDb, SdkTools, SdkSetup, FxTools]

    def checkpath(path, varlist):
        # Function that add valid paths in list in not already present
        if os.path.isdir(path) and path not in varlist:
            varlist.append(path)

    for key in env.keys():
        var = []
        # Add valid paths
        for val in env[key]:
            for subval in val:
                checkpath(subval, var)

        # Add values from actual environment
        try:
            for val in os.environ[key].split(';'):
                checkpath(val, var)
        except KeyError:
            pass

        # Format paths to Environment Variable string
        if var:
            env[key] = ';'.os.path.join(var)
        else:
            msg = "%s environment variable is empty" % key.upper()
            raise distutils.errors.DistutilsPlatformError(msg)
    return env
