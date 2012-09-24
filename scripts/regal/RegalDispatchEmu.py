#!/usr/bin/python -B

from string import Template, upper, replace

from ApiUtil import outputCode
from ApiUtil import typeIsVoid

from ApiCodeGen import *

from Regal            import debugPrintFunction
from RegalContext     import emu
from RegalContextInfo import cond

from Emu       import emuFindEntry, emuCodeGen

##############################################################################################

dispatchSourceTemplate = Template('''${AUTOGENERATED}
${LICENSE}

#include "pch.h" /* For MS precompiled header support */

#include "RegalUtil.h"

${IFDEF}REGAL_GLOBAL_BEGIN

#include <string>
using namespace std;

#include "RegalLog.h"
#include "RegalPush.h"
#include "RegalToken.h"
#include "RegalHelper.h"
#include "RegalPrivate.h"
#include "RegalContext.h"
${LOCAL_INCLUDE}

REGAL_GLOBAL_END

REGAL_NAMESPACE_BEGIN

using namespace ::REGAL_NAMESPACE_INTERNAL::Logging;
using namespace ::REGAL_NAMESPACE_INTERNAL::Token;

${LOCAL_CODE}

${API_DISPATCH_FUNC_DEFINE}

void InitDispatchTable${DISPATCH_NAME}(DispatchTable &tbl)
{
  ${API_DISPATCH_FUNC_INIT}
}

REGAL_NAMESPACE_END

${ENDIF}''')

# CodeGen for API emu function definition.

def apiEmuFuncDefineCode(apis, args):
    categoryPrev = None
    code = ''

    for api in apis:

        code += '\n'
        if api.name in cond:
            code += '#if %s\n' % cond[api.name]

        for function in api.functions:
            if not function.needsContext:
                continue
            if getattr(function,'regalOnly',False)==True:
              continue

            name   = function.name
            params = paramsDefaultCode(function.parameters, True)
            callParams = paramsNameCode(function.parameters)
            rType  = typeCode(function.ret.type)
            category  = getattr(function, 'category', None)
            version   = getattr(function, 'version', None)

            if category:
                category = category.replace('_DEPRECATED', '')
            elif version:
                category = version.replace('.', '_')
                category = 'GL_VERSION_' + category

            # Close prev category block.
            if categoryPrev and not (category == categoryPrev):
                code += '\n'

            # Begin new category block.
            if category and not (category == categoryPrev):
                code += '// %s\n\n' % category

            categoryPrev = category

            emue = [ emuFindEntry( function, i['formulae'], i['member'] ) for i in emu ]

            if all(i is None for i in emue) and (getattr(function,'regalRemap',None)==None or isinstance(function.regalRemap, str) or isinstance(function.regalRemap, unicode)):
                continue

            code += '\nstatic %sREGAL_CALL %s%s(%s) \n{\n' % (rType, 'emu_', name, params)
            code += '   RegalContext *_context = GET_REGAL_CONTEXT();\n'
            code += '   RegalAssert(_context);\n'
            code += '\n'

            level = [ (emu[i], emuFindEntry( function, emu[i]['formulae'], emu[i]['member'] )) for i in range( len( emue ) - 1 ) ]

            if not all(i[1]==None or not 'prefix' in i[1] and not 'impl' in i[1] for i in level):
              code += '   // prefix\n'
              code += '   switch( _context->emuLevel ) {\n'
              for i in level:
                  l,e = i[0], i[1]
                  code += '       case %d :\n' % l['level']
                  if l['ifdef']:
                      code += '         #if %s\n' % l['ifdef']
                  if e != None and 'prefix' in e and len(e['prefix']):
                      if l['member'] :
                          code += '         if (_context->%s) {\n' % l['member']
                          code += '             RegalEmuScopedActivate activate( _context, _context->%s );\n' % l['member']
                      for j in e['prefix'] :
                          code += '             %s\n' % j
                      if l['member'] :
                          code += '         }\n'
                  if e!= None and 'impl' in e and l['member']:
                      code += '         if (_context->%s) break;\n' % l['member'];
                  if l['ifdef']:
                      code += '         #endif\n'
              code += '       default:\n'
              code += '           break;\n'
              code += '   }\n\n'

            # Remap, as necessary
            remap = getattr(function, 'regalRemap', None)
            es2Name = None
            if remap != None:
              es2Name = remap.get('ES2.0',None)
              es2Params = callParams
              if es2Name != None:
                j = es2Name.find('(')
                if j!=-1:
                  es2Params = es2Name[j+1:-1]
                  es2Name   = es2Name[0:j]

            if not all(i[1]==None or not 'impl' in i[1] for i in level):
              code += '   // impl\n'
              code += '   switch( _context->emuLevel ) {\n'
              for i in level:
                  l,e = i[0], i[1]
                  code += '       case %d :\n' % l['level']
                  if l['ifdef']:
                      code += '         #if %s\n' % l['ifdef']
                  if e != None and 'impl' in e and len(e['impl']):
                      if l['member'] :
                        code += '         if (_context->%s) {\n' % l['member']
                        code += '             RegalEmuScopedActivate activate( _context, _context->%s );\n' % l['member']
                      for j in e['impl'] :
                          code += '             %s\n' % j
                      if l['member'] :
                          if typeIsVoid(rType):
                              code += '             return;\n'
                          code += '         }\n'
                  if l['ifdef']:
                      code += '         #endif\n'
              code += '       default: {\n'

              # glEnable/glDisable/glIsEnabled constraints for ES 2.0
              # http://www.khronos.org/opengles/sdk/docs/man/xhtml/glEnable.xml

              if name=='glEnable' or name=='glDisable' or name=='glIsEnabled':
                code += '         if (_context->info->gles)\n'
                code += '           switch (cap)\n'
                code += '           {\n'
                for i in api.enums:
                  if i.name=='defines':
                    for j in i.enumerants:
                      if getattr(j,'esVersions',None) != None and getattr(j,'enableCap',None) != None and 2.0 in j.esVersions and j.enableCap == True:
                        code += '             case %s:\n'%(j.name)
                code += '               break;\n'
                code += '             default:\n'
                code += '               Warning("%s does not support ",GLenumToString(cap)," for ES 2.0.");\n'%(name)
                if name=='glIsEnabled':
                  code += '               return GL_FALSE;\n'
                else:
                  code += '               return;\n'
                code += '           }\n'

              # glHint constraints for ES 2.0
              # http://www.khronos.org/opengles/sdk/docs/man/xhtml/glHint.xml

              if name=='glHint':
                code += '         if (_context->info->gles)\n'
                code += '           switch (target)\n'
                code += '           {\n'
                for i in api.enums:
                  if i.name=='defines':
                    for j in i.enumerants:
                      if getattr(j,'esVersions',None)==None:
                        continue
                      if getattr(j,'hint',None)==None:
                        continue
                      if getattr(j,'esVersions',None) != None and getattr(j,'hint',None) != None and 2.0 in j.esVersions and j.hint == True:
                        code += '             case %s:\n'%(j.name)
                code += '               break;\n'
                code += '             default:\n'
                code += '               Warning("%s does not support ",GLenumToString(target)," for ES 2.0.");\n'%(name)
                code += '               return;\n'
                code += '           }\n'

              code += '         DispatchTable *_next = _context->dispatcher.emulation._next;\n'
              code += '         RegalAssert(_next);\n'

              if es2Name != None:
                code += '         '
                code += 'if (_context->info->gles)\n'
                code += '         '
                if not typeIsVoid(rType):
                    code += '  return '
                code += '  _next->call(&_next->%s)(%s);\n' % ( es2Name, es2Params )
                code += '         else\n  '

              code += '         '
              if not typeIsVoid(rType):
                  code += 'return '
              code += ' _next->call(&_next->%s)(%s);\n' % ( name, callParams )

              code += '         break;\n'
              code += '       }\n\n'
              code += '   }\n\n'
            else:
              code += '   DispatchTable *_next = _context->dispatcher.emulation._next;\n'
              code += '   RegalAssert(_next);\n'
              code += '   '

              if es2Name != None:
                code += 'if (_context->info->gles)\n'
                code += '     '
                if not typeIsVoid(rType):
                    code += 'return '
                code += ' _next->call(& _next->%s)(%s);\n' % ( es2Name, es2Params )
                code += '   else\n     '

              if not typeIsVoid(rType):
                  code += 'return '
              code += ' _next->call(& _next->%s)(%s);\n' % ( name, callParams )
            code += '}\n\n'

        if api.name in cond:
            code += '#endif // %s\n' % cond[api.name]
        code += '\n'

    # Close pending if block.
    if categoryPrev:
        code += '\n'

    return code

# CodeGen for dispatch table init.

def apiEmuDispatchFuncInitCode(apis, args):
  dispatchName = 'emu'
  categoryPrev = None
  code = ''

  for api in apis:

    code += '\n'
    if api.name in cond:
      code += '#if %s\n' % cond[api.name]

    for function in api.functions:
      if not function.needsContext:
        continue
      if getattr(function,'regalOnly',False)==True:
        continue

      name   = function.name

      emue = [ None ]
      for i in range( len( emu ) - 1 ) :
        emue.append( emuFindEntry( function, emu[i]['formulae'], emu[i]['member'] ) )

      if all(i is None for i in emue) and (getattr(function,'regalRemap',None)==None or isinstance(function.regalRemap, str) or isinstance(function.regalRemap, unicode)):
        continue

      params = paramsDefaultCode(function.parameters, True)
      callParams = paramsNameCode(function.parameters)
      rType  = typeCode(function.ret.type)
      category  = getattr(function, 'category', None)
      version   = getattr(function, 'version', None)

      if category:
        category = category.replace('_DEPRECATED', '')
      elif version:
        category = version.replace('.', '_')
        category = 'GL_VERSION_' + category

      # Close prev category block.
      if categoryPrev and not (category == categoryPrev):
        code += '\n'

      # Begin new category block.
      if category and not (category == categoryPrev):
        code += '// %s\n\n' % category

      categoryPrev = category

      code += '   tbl.%s = %s_%s;\n' % ( name, dispatchName, name )

    if api.name in cond:
      code += '#endif // %s\n' % cond[api.name]
    code += '\n'

  # Close pending if block.
  if categoryPrev:
    code += '\n'

  return code

emuLocalCode = '''


'''



def generateEmuSource(apis, args):

  funcDefine = apiEmuFuncDefineCode( apis, args )
  funcInit   = apiEmuDispatchFuncInitCode( apis, args )

  emuLocalInclude = '''

#include "RegalBin.h"
#include "RegalEmu.h"
#include "RegalPpa.h"
#include "RegalIff.h"
#include "RegalMarker.h"
#include "RegalObj.h"
#include "RegalDsa.h"
#include "RegalVao.h"'''

  # Output

  substitute = {}
  substitute['LICENSE']         = args.license
  substitute['AUTOGENERATED']   = args.generated
  substitute['COPYRIGHT']       = args.copyright
  substitute['DISPATCH_NAME']   = 'Emu'
  substitute['LOCAL_CODE']      = emuLocalCode
  substitute['LOCAL_INCLUDE']   = emuLocalInclude
  substitute['API_DISPATCH_FUNC_DEFINE'] = funcDefine
  substitute['API_DISPATCH_FUNC_INIT'] = funcInit
  substitute['IFDEF'] = '#if REGAL_EMULATION\n\n'
  substitute['ENDIF'] = '#endif\n'

  outputCode( '%s/RegalDispatchEmu.cpp' % args.outdir, dispatchSourceTemplate.substitute(substitute))
